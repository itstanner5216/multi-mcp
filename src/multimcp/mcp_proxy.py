from typing import TYPE_CHECKING, Any, Optional
import asyncio
from mcp import server, types
from mcp.client.session import ClientSession
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INVALID_PARAMS, INTERNAL_ERROR
from src.utils.logger import get_logger
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.utils.audit import AuditLogger
from src.multimcp.mcp_trigger_manager import MCPTriggerManager
from dataclasses import dataclass

if TYPE_CHECKING:
    from src.multimcp.retrieval.pipeline import RetrievalPipeline


@dataclass
class ToolMapping:
    server_name: str
    client: Optional[ClientSession]  # None = server not yet connected (lazy/pending)
    tool: types.Tool


@dataclass
class PromptMapping:
    server_name: str
    client: Optional[ClientSession]
    prompt: types.Prompt


@dataclass
class ResourceMapping:
    server_name: str
    client: Optional[ClientSession]
    resource: types.Resource


class MCPProxyServer(server.Server):
    """An MCP Proxy Server that forwards requests to remote MCP servers."""

    def __init__(self, client_manager: MCPClientManager):
        super().__init__("MultiMCP proxy Server")
        self.capabilities: dict[str, types.ServerCapabilities] = {}
        self.tool_to_server: dict[
            str, ToolMapping
        ] = {}  # Support same tool name in different mcp server
        self.prompt_to_server: dict[str, PromptMapping] = {}
        self.resource_to_server: dict[str, ResourceMapping] = {}
        self._register_lock = asyncio.Lock()  # Lock for concurrent register/unregister
        self._register_request_handlers()
        self.logger = get_logger("multi_mcp.ProxyServer")
        self.client_manager: Optional[MCPClientManager] = client_manager
        # Initialize audit logger
        self.audit_logger = AuditLogger()
        # Store active server session for sending notifications
        self._server_session: Optional[ServerSession] = None
        # Initialize trigger manager
        self.trigger_manager = MCPTriggerManager(client_manager)
        # Optional retrieval pipeline (None = passthrough, all tools returned)
        self.retrieval_pipeline: Optional["RetrievalPipeline"] = None

    @classmethod
    async def create(cls, client_manager: MCPClientManager) -> "MCPProxyServer":
        """Factory method to create and initialize the proxy with clients."""
        proxy = cls(client_manager)
        await proxy.initialize_remote_clients()
        return proxy

    def load_tools_from_yaml(self, yaml_config: "MultiMCPConfig") -> None:
        """Pre-populate tool_to_server from YAML cache with client=None placeholders.

        This allows tools to be listed immediately at startup without waiting for
        server connections. When a tool is called, the server connects on demand.
        Skips servers that already have live clients (avoids overwriting real entries).
        """
        from src.multimcp.cache_manager import get_enabled_tools
        for server_name, server_config in yaml_config.servers.items():
            # Don't overwrite entries already populated by live initialization
            existing_keys = {
                k for k, v in self.tool_to_server.items()
                if v.server_name == server_name and v.client is not None
            }
            if existing_keys:
                continue
            enabled = get_enabled_tools(yaml_config, server_name)
            for tool_name, tool_entry in server_config.tools.items():
                if tool_name not in enabled:
                    continue
                key = self._make_key(server_name, tool_name)
                if key in self.tool_to_server:
                    continue
                cached_tool = types.Tool(
                    name=key,
                    description=tool_entry.description,
                    inputSchema=(
                        tool_entry.input_schema
                        if tool_entry.input_schema is not None
                        else {"type": "object", "properties": {}}
                    ),
                )
                self.tool_to_server[key] = ToolMapping(
                    server_name=server_name,
                    client=None,
                    tool=cached_tool,
                )

    async def initialize_remote_clients(self) -> None:
        """Initialize all remote clients and store their capabilities."""
        failed = []
        for name, client in self.client_manager.clients.items():
            try:
                await self.initialize_single_client(name, client)
            except Exception as e:
                self.logger.error(f"❌ Failed to initialize client {name}: {e}")
                failed.append(name)
        # Remove failed clients so their broken sessions don't crash tool listing
        for name in failed:
            self.client_manager.clients.pop(name, None)
            self.client_manager.server_stacks.pop(name, None)

    async def initialize_single_client(self, name: str, client: ClientSession) -> None:
        """Initialize a specific client and map its capabilities."""

        # Validate name doesn't contain separator
        if "__" in name:
            raise ValueError(f"Server name '{name}' cannot contain '__' separator")

        self.logger.info(f"try initialize client {name}: {client}")
        result = await client.initialize()
        self.capabilities[name] = result.capabilities

        if result.capabilities.tools:
            await self._initialize_tools_for_client(name, client)

        if result.capabilities.prompts:
            try:
                prompts_result = await client.list_prompts()
                for prompt in prompts_result.prompts:
                    if "__" in prompt.name:
                        continue
                    key = self._make_key(name, prompt.name)
                    self.prompt_to_server[key] = PromptMapping(
                        server_name=name, client=client, prompt=prompt
                    )
            except Exception as e:
                self.logger.warning(f"⚠️ '{name}' advertises prompts but list_prompts failed: {e}")

        if result.capabilities.resources:
            try:
                resources_result = await client.list_resources()
                for resource in resources_result.resources:
                    resource_key = resource.name if resource.name else resource.uri
                    if "__" in resource_key:
                        continue
                    uri_str = str(resource.uri)
                    self.resource_to_server[uri_str] = ResourceMapping(
                        server_name=name, client=client, resource=resource
                    )
            except Exception as e:
                self.logger.warning(f"⚠️ '{name}' advertises resources but list_resources failed: {e}")

    async def register_client(self, name: str, client: ClientSession) -> None:
        """Add a new client and register its capabilities."""
        async with self._register_lock:
            self.client_manager.clients[name] = client
            # Re-fetch capabilities (like on startup)
            await self.initialize_single_client(name, client)
            # Send notifications for changed capabilities
            caps = self.capabilities.get(name)
            if caps and caps.tools:
                await self._send_tools_list_changed()
            if caps and caps.prompts:
                await self._send_prompts_list_changed()
            if caps and caps.resources:
                await self._send_resources_list_changed()

    async def unregister_client(self, name: str) -> None:
        """Remove a client and clean up all its associated mappings."""
        async with self._register_lock:
            client = self.client_manager.clients.get(name)
            if not client:
                self.logger.warning(f"⚠️ Tried to unregister unknown client: {name}")
                return

            # Check if client had tools capability before removing
            caps = self.capabilities.get(name)
            had_tools = caps and caps.tools if caps else False

            self.logger.info(f"🗑️ Unregistering client: {name}")
            del self.client_manager.clients[name]

            self.capabilities.pop(name, None)

            # Fix: filter by server_name, not client identity.
            # After disconnect, client is set to None, so v.client != client
            # would be True (None != original_client), keeping ghost entries.
            self.tool_to_server = {
                k: v for k, v in self.tool_to_server.items() if v.server_name != name
            }
            self.prompt_to_server = {
                k: v for k, v in self.prompt_to_server.items() if v.server_name != name
            }
            self.resource_to_server = {
                k: v for k, v in self.resource_to_server.items() if v.server_name != name
            }

            self.logger.info(f"✅ Client '{name}' fully unregistered.")

            # Clean up client manager runtime state for this server
            if self.client_manager:
                self.client_manager.tool_filters.pop(name, None)
                self.client_manager.idle_timeouts.pop(name, None)
                self.client_manager.last_used.pop(name, None)
                self.client_manager._creation_locks.pop(name, None)

            # Send notifications for removed capabilities
            if had_tools:
                await self._send_tools_list_changed()
            had_prompts = caps and caps.prompts if caps else False
            if had_prompts:
                await self._send_prompts_list_changed()
            had_resources = caps and caps.resources if caps else False
            if had_resources:
                await self._send_resources_list_changed()
    ## Tools capabilities
    async def _list_tools(self, _: Any) -> types.ServerResult:
        """Return the cached tool list. Tools are registered during initialization
        and updated dynamically when servers are added/removed.
        When a retrieval pipeline is configured, delegates to it for filtering."""
        if self.retrieval_pipeline is not None:
            # TODO: extract real session_id from MCP request context when available
            tools = await self.retrieval_pipeline.get_tools_for_list("default")
            return types.ServerResult(tools=tools)
        all_tools = [mapping.tool for mapping in self.tool_to_server.values()]
        return types.ServerResult(tools=all_tools)

    def get_filtered_tools(self) -> dict[str, list[str]]:
        """Return the filtered tool list grouped by server (same view as MCP tools/list).

        Uses the proxy's tool_to_server registry which already has filters applied.
        Includes cached tools (client=None) to match the MCP protocol tools/list
        behavior — tools are visible before servers connect.
        """
        tools_by_server: dict[str, list[str]] = {}
        for key, mapping in self.tool_to_server.items():
            server = mapping.server_name
            _, tool_name = self._split_key(key)
            if server not in tools_by_server:
                tools_by_server[server] = []
            tools_by_server[server].append(tool_name)
        return tools_by_server

    async def _call_tool(self, req: types.CallToolRequest) -> types.ServerResult:
        """Invoke a tool on the correct backend MCP server."""
        tool_name = req.params.name
        tool_item = self.tool_to_server.get(tool_name)
        arguments = req.params.arguments or {}

        # Check for keyword triggers and auto-enable matching servers
        message = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        enabled_servers = await self.trigger_manager.check_and_enable(message)

        # If servers were enabled, register them with the proxy
        for server_name in enabled_servers:
            client = self.client_manager.clients.get(server_name)
            if client:
                await self.initialize_single_client(server_name, client)
                self.logger.info(f"🔥 Auto-enabled server '{server_name}' via trigger")

        # Re-check tool_to_server in case new tool was just enabled
        if not tool_item:
            tool_item = self.tool_to_server.get(tool_name)

        if tool_item:
            # If client is None (cached from YAML, server not yet connected), connect now
            if tool_item.client is None:
                try:
                    self.logger.info(f"🔌 Connecting '{tool_item.server_name}' on first tool call...")
                    client = await self.client_manager.get_or_create_client(tool_item.server_name)
                    await self.initialize_single_client(tool_item.server_name, client)
                    await self._send_tools_list_changed()
                    tool_item = self.tool_to_server.get(tool_name)
                except Exception as e:
                    return types.ServerResult(
                        content=[types.TextContent(type="text", text=f"Failed to connect server '{tool_item.server_name}': {e}")],
                        isError=True,
                    )

            if tool_item is None or tool_item.client is None:
                return types.ServerResult(
                    content=[types.TextContent(type="text", text=f"Tool '{tool_name}' server failed to connect.")],
                    isError=True,
                )

            try:
                self.logger.info(
                    f"✅ Calling tool '{tool_name}' on its associated server"
                )
                _, original_name = self._split_key(tool_name)
                result = await tool_item.client.call_tool(
                    original_name, arguments
                )

                # Log successful tool invocation (use original name for cross-referencing)
                self.audit_logger.log_tool_call(
                    tool_name=original_name,
                    server_name=tool_item.server_name,
                    arguments=arguments,
                )

                # Refresh idle timer so active servers aren't evicted
                if self.client_manager:
                    self.client_manager.record_usage(tool_item.server_name)

                # Notify retrieval pipeline of tool usage (progressive disclosure)
                if self.retrieval_pipeline is not None:
                    try:
                        disclosed = await self.retrieval_pipeline.on_tool_called(
                            "default", tool_name, arguments
                        )
                        if disclosed:
                            await self._send_tools_list_changed()
                    except Exception as e:
                        self.logger.warning(f"⚠️ Retrieval pipeline error on tool call: {e}")

                return types.ServerResult(result)
            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"❌ Failed to call tool '{tool_name}': {e}")

                # Log tool failure (use original name for cross-referencing)
                self.audit_logger.log_tool_failure(
                    tool_name=original_name,
                    server_name=tool_item.server_name,
                    arguments=arguments,
                    error=error_msg,
                )

                # Return error to client
                return types.ServerResult(
                    content=[
                        types.TextContent(
                            type="text", text=f"Tool '{tool_name}' failed: {error_msg}"
                        )
                    ],
                    isError=True,
                )
        else:
            self.logger.error(f"⚠️ Tool '{tool_name}' not found in any server.")

            # Log tool not found as failure (no server name since tool doesn't exist)
            self.audit_logger.log_tool_failure(
                tool_name=tool_name,
                server_name="unknown",
                arguments=arguments,
                error=f"Tool '{tool_name}' not found in any server",
            )

        return types.ServerResult(
            content=[
                types.TextContent(type="text", text=f"Tool '{tool_name}' not found!")
            ],
            isError=True,
        )

    ## Prompts capabilities
    async def _list_prompts(self, _: Any) -> types.ServerResult:
        """Return cached prompts from all remote MCP servers with namespacing."""
        all_prompts = []
        for key, mapping in self.prompt_to_server.items():
            namespaced_prompt = mapping.prompt.model_copy()
            namespaced_prompt.name = key
            all_prompts.append(namespaced_prompt)
        return types.ServerResult(prompts=all_prompts)

    async def _get_prompt(self, req: types.GetPromptRequest) -> types.ServerResult:
        """Fetch a specific prompt from the correct backend MCP server."""
        prompt_name = req.params.name
        mapping = self.prompt_to_server.get(prompt_name)

        if mapping and mapping.client:
            try:
                _, original_name = self._split_key(prompt_name)
                result = await mapping.client.get_prompt(original_name, req.params.arguments)
            except Exception as e:
                self.logger.error(f"❌ Failed to get prompt '{prompt_name}': {e}")
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to get prompt '{prompt_name}': {e}"))
            return types.ServerResult(result)

        self.logger.error(f"⚠️ Prompt '{prompt_name}' not found in any server.")
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Prompt '{prompt_name}' not found"))

    async def _complete(self, req: types.CompleteRequest) -> types.ServerResult:
        """Execute a prompt completion on the relevant MCP server."""
        prompt_name = None
        mapping = None
        if hasattr(req.params.ref, 'name'):
            prompt_name = req.params.ref.name
            mapping = self.prompt_to_server.get(prompt_name)

        if mapping and mapping.client:
            try:
                ref = req.params.ref
                if hasattr(ref, 'name'):
                    _, original_name = self._split_key(ref.name)
                    ref = ref.model_copy(update={"name": original_name})
                result = await mapping.client.complete(ref, req.params.argument)
            except Exception as e:
                self.logger.error(f"❌ Failed to complete prompt '{prompt_name}': {e}")
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to complete prompt '{prompt_name}': {e}"))
            return types.ServerResult(result)

        ref_desc = prompt_name or str(getattr(req.params.ref, 'uri', 'unknown'))
        self.logger.error(f"⚠️ Prompt '{ref_desc}' not found for completion.")
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Prompt '{ref_desc}' not found for completion"))

    ## Resources capabilities
    async def _list_resources(self, _: Any) -> types.ServerResult:
        """Return cached resources from all remote MCP servers."""
        all_resources = []
        for key, mapping in self.resource_to_server.items():
            namespaced_resource = mapping.resource.model_copy()
            # Prefix name with server for disambiguation; URI stays raw for lookups
            original_name = namespaced_resource.name or str(namespaced_resource.uri)
            namespaced_resource.name = self._make_key(mapping.server_name, original_name)
            all_resources.append(namespaced_resource)
        return types.ServerResult(resources=all_resources)

    async def _read_resource(
        self, req: types.ReadResourceRequest
    ) -> types.ServerResult:
        """Read a resource from the appropriate backend MCP server."""
        resource_uri = str(req.params.uri)
        mapping = self.resource_to_server.get(resource_uri)

        if mapping and mapping.client:
            try:
                # Resource keys are raw URIs (not namespaced) — pass directly to backend
                result = await mapping.client.read_resource(resource_uri)
            except Exception as e:
                self.logger.error(f"❌ Failed to read resource '{resource_uri}': {e}")
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to read resource '{resource_uri}': {e}"))
            return types.ServerResult(result)

        self.logger.error(f"⚠️ Resource '{resource_uri}' not found in any server.")
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Resource '{resource_uri}' not found"))

    async def _subscribe_resource(
        self, req: types.SubscribeRequest
    ) -> types.ServerResult:
        """Subscribe to a resource for updates on a backend MCP server."""
        uri = str(req.params.uri)
        mapping = self.resource_to_server.get(uri)

        if mapping and mapping.client:
            try:
                # Resource keys are raw URIs (not namespaced) — pass directly to backend
                await mapping.client.subscribe_resource(uri)
                return types.ServerResult(types.EmptyResult())
            except Exception as e:
                self.logger.error(f"❌ Failed to subscribe to resource '{uri}': {e}")
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to subscribe to resource '{uri}': {e}"))

        self.logger.error(f"⚠️ Resource '{uri}' not found for subscription.")
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Resource '{uri}' not found for subscription"))

    async def _unsubscribe_resource(
        self, req: types.UnsubscribeRequest
    ) -> types.ServerResult:
        """Unsubscribe from a previously subscribed resource."""
        uri = str(req.params.uri)
        mapping = self.resource_to_server.get(uri)

        if mapping and mapping.client:
            try:
                # Resource keys are raw URIs (not namespaced) — pass directly to backend
                await mapping.client.unsubscribe_resource(uri)
                return types.ServerResult(types.EmptyResult())
            except Exception as e:
                self.logger.error(
                    f"❌ Failed to unsubscribe from resource '{uri}': {e}"
                )
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to unsubscribe from resource '{uri}': {e}"))

        self.logger.error(f"⚠️ Resource '{uri}' not found for unsubscription.")
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Resource '{uri}' not found for unsubscription"))

    def _register_request_handlers(self) -> None:
        """Dynamically registers handlers for all MCP requests."""

        # Register all request handlers
        self.request_handlers[types.ListPromptsRequest] = self._list_prompts
        self.request_handlers[types.GetPromptRequest] = self._get_prompt
        self.request_handlers[types.CompleteRequest] = self._complete

        self.request_handlers[types.ListResourcesRequest] = self._list_resources
        self.request_handlers[types.ReadResourceRequest] = self._read_resource
        self.request_handlers[types.SubscribeRequest] = self._subscribe_resource
        self.request_handlers[types.UnsubscribeRequest] = self._unsubscribe_resource

        self.request_handlers[types.ListToolsRequest] = self._list_tools
        self.request_handlers[types.CallToolRequest] = self._call_tool

        # NOTE: ProgressNotification and SetLevelRequest handlers removed.
        # MCP progress flows server→client (not client→server), so relaying
        # client progress to backends is wrong direction per spec.
        # SetLevelRequest could be valid for a proxy but is unused by any
        # known MCP client. Re-add if a real use case emerges.

    async def _initialize_tools_for_client(
        self, server_name: str, client: ClientSession
    ) -> list[types.Tool]:
        """Fetch tools from a client, populate tool_to_server, and return them with namespaced keys."""
        tool_list = []
        tool_filter = (
            self.client_manager.tool_filters.get(server_name)
            if self.client_manager
            else None
        )

        tools_result = await client.list_tools()
        for tool in tools_result.tools:
            if not self._is_tool_allowed(tool.name, tool_filter):
                self.logger.debug(
                    f"🚫 Filtered out '{tool.name}' from '{server_name}'"
                )
                continue

            key = self._make_key(server_name, tool.name)

            # Create a copy of the tool with namespaced key as name
            namespaced_tool = tool.model_copy()
            namespaced_tool.name = key

            # Store ToolMapping with namespaced tool (consistent with load_tools_from_yaml)
            self.tool_to_server[key] = ToolMapping(
                server_name=server_name, client=client, tool=namespaced_tool
            )

            tool_list.append(namespaced_tool)

        return tool_list

    @staticmethod
    def _is_tool_allowed(tool_name: str, filter_config: Optional[dict]) -> bool:
        """Return True if the tool should be exposed given the filter config."""
        if filter_config is None:
            return True
        deny = filter_config.get("deny", [])
        if "*" in deny or tool_name in deny:
            return False
        allow = filter_config.get("allow", ["*"])
        if not allow:   # Empty allow list = deny all
            return False
        return "*" in allow or tool_name in allow

    @staticmethod
    def _make_key(server_name: str, item_name: str) -> str:
        """Returns a namespaced key like 'server__item' to uniquely identify items per server."""
        return f"{server_name}__{item_name}"

    @staticmethod
    def _split_key(key: str) -> tuple[str, str]:
        """Splits a namespaced key back into (server, item)."""
        parts = key.split("__", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid namespaced key: {key}")
        return (parts[0], parts[1])

    async def _on_server_disconnected(self, server_name: str) -> None:
        """Reset tool, prompt, and resource mappings for a disconnected server and notify client."""
        async with self._register_lock:
            for key, mapping in self.tool_to_server.items():
                if mapping.server_name == server_name:
                    mapping.client = None
            for key, mapping in self.prompt_to_server.items():
                if mapping.server_name == server_name:
                    mapping.client = None
            for key, mapping in self.resource_to_server.items():
                if mapping.server_name == server_name:
                    mapping.client = None
        await self._send_tools_list_changed()
        await self._send_prompts_list_changed()
        await self._send_resources_list_changed()
        self.logger.info(f"🔄 Reset tool, prompt, and resource mappings for disconnected server '{server_name}'")

    async def _send_tools_list_changed(self) -> None:
        """Send tools/list_changed notification if a session is active."""
        if self._server_session:
            try:
                await self._server_session.send_tool_list_changed()
                self.logger.info("📢 Sent tools/list_changed notification")
            except Exception as e:
                self.logger.error(
                    f"❌ Failed to send tools/list_changed notification: {e}"
                )
        else:
            self.logger.debug(
                "⚠️ No active session to send tools/list_changed notification"
            )

    async def _send_prompts_list_changed(self) -> None:
        """Send prompts/list_changed notification if a session is active."""
        if self._server_session:
            try:
                await self._server_session.send_prompts_list_changed()
                self.logger.info("📢 Sent prompts/list_changed notification")
            except Exception as e:
                self.logger.error(
                    f"❌ Failed to send prompts/list_changed notification: {e}"
                )
        else:
            self.logger.debug(
                "⚠️ No active session to send prompts/list_changed notification"
            )

    async def _send_resources_list_changed(self) -> None:
        """Send resources/list_changed notification if a session is active."""
        if self._server_session:
            try:
                await self._server_session.send_resources_list_changed()
                self.logger.info("📢 Sent resources/list_changed notification")
            except Exception as e:
                self.logger.error(
                    f"❌ Failed to send resources/list_changed notification: {e}"
                )
        else:
            self.logger.debug(
                "⚠️ No active session to send resources/list_changed notification"
            )

    async def run(
        self,
        read_stream,
        write_stream,
        initialization_options,
        raise_exceptions: bool = False,
    ):
        """Override run to capture the server session for notifications.
        
        NOTE(M8): This method intentionally does NOT call super().run().
        Instead, it reimplements the session lifecycle to capture the ServerSession
        reference needed for sending tool/prompt/resource list_changed notifications.
        The base class run() doesn't expose the session object, so we must manage
        the session context directly to retain a reference in self._server_session.
        """
        # Import here to avoid circular dependencies
        from mcp.server.session import ServerSession
        from contextlib import AsyncExitStack
        import anyio

        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(self.lifespan(self))
            session = await stack.enter_async_context(
                ServerSession(read_stream, write_stream, initialization_options)
            )

            # Store session reference for sending notifications
            self._server_session = session
            self.logger.debug("🔗 Server session stored for notifications")

            # Call parent's message handling loop
            async with anyio.create_task_group() as tg:
                async for message in session.incoming_messages:
                    self.logger.debug(f"Received message: {message}")

                    tg.start_soon(
                        self._handle_message,
                        message,
                        session,
                        lifespan_context,
                        raise_exceptions,
                    )

            # Clear session when done
            self._server_session = None
