from typing import Any, Optional
import asyncio
from mcp import server, types
from mcp.client.session import ClientSession
from mcp.server.session import ServerSession
from src.utils.logger import get_logger
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.utils.audit import AuditLogger
from src.multimcp.mcp_trigger_manager import MCPTriggerManager
from dataclasses import dataclass


@dataclass
class ToolMapping:
    server_name: str
    client: Optional[ClientSession]  # None = server not yet connected (lazy/pending)
    tool: types.Tool


class MCPProxyServer(server.Server):
    """An MCP Proxy Server that forwards requests to remote MCP servers."""

    def __init__(self, client_manager: MCPClientManager):
        super().__init__("MultiMCP proxy Server")
        self.capabilities: dict[str, types.ServerCapabilities] = {}
        self.tool_to_server: dict[
            str, ToolMapping
        ] = {}  # Support same tool name in different mcp server
        self.prompt_to_server: dict[str, ClientSession] = {}
        self.resource_to_server: dict[str, ClientSession] = {}
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
                    inputSchema={"type": "object", "properties": {}},
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
                    self.prompt_to_server[key] = client
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
                    self.resource_to_server[uri_str] = client
            except Exception as e:
                self.logger.warning(f"⚠️ '{name}' advertises resources but list_resources failed: {e}")

    async def register_client(self, name: str, client: ClientSession) -> None:
        """Add a new client and register its capabilities."""
        async with self._register_lock:
            self.client_manager.clients[name] = client
            # Re-fetch capabilities (like on startup)
            await self.initialize_single_client(name, client)
            # Send notification if server has tools capability
            caps = self.capabilities.get(name)
            if caps and caps.tools:
                await self._send_tools_list_changed()

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

            # Fix: correct filter condition - remove entries where client matches
            self.tool_to_server = {
                k: v for k, v in self.tool_to_server.items() if v.client != client
            }
            self.prompt_to_server = {
                k: v for k, v in self.prompt_to_server.items() if v != client
            }
            self.resource_to_server = {
                k: v for k, v in self.resource_to_server.items() if v != client
            }

            self.logger.info(f"✅ Client '{name}' fully unregistered.")

            # Send notification if client had tools capability
            if had_tools:
                await self._send_tools_list_changed()

    ## Tools capabilities
    async def _list_tools(self, _: Any) -> types.ServerResult:
        """Return the cached tool list. Tools are registered during initialization
        and updated dynamically when servers are added/removed."""
        all_tools = [mapping.tool for mapping in self.tool_to_server.values() if mapping.client is not None]
        return types.ServerResult(tools=all_tools)

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

                # Log successful tool invocation
                self.audit_logger.log_tool_call(
                    tool_name=tool_name,
                    server_name=tool_item.server_name,
                    arguments=arguments,
                )

                return types.ServerResult(result)
            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"❌ Failed to call tool '{tool_name}': {e}")

                # Log tool failure
                self.audit_logger.log_tool_failure(
                    tool_name=tool_name,
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
        """Aggregate prompts from all remote MCP servers and return a combined list with namespacing."""
        all_prompts = []
        for name, client in self.client_manager.clients.items():
            # Only call servers that support prompts capability
            caps = self.capabilities.get(name)
            if not caps or not caps.prompts:
                continue
            try:
                prompts_result = await client.list_prompts()
                # Namespace each prompt
                for prompt in prompts_result.prompts:
                    namespaced_prompt = prompt.model_copy()
                    namespaced_prompt.name = self._make_key(name, prompt.name)
                    all_prompts.append(namespaced_prompt)
            except Exception as e:
                self.logger.error(f"Error fetching prompts from {name}: {e}")

        return types.ServerResult(prompts=all_prompts)

    async def _get_prompt(self, req: types.GetPromptRequest) -> types.ServerResult:
        """Fetch a specific prompt from the correct backend MCP server."""
        prompt_name = req.params.name
        client = self.prompt_to_server.get(prompt_name)

        if client:
            try:
                _, original_name = self._split_key(prompt_name)
                result = await client.get_prompt(original_name, req.params.arguments)
                return types.ServerResult(result)
            except Exception as e:
                self.logger.error(f"❌ Failed to get prompt '{prompt_name}': {e}")
        else:
            self.logger.error(f"⚠️ Prompt '{prompt_name}' not found in any server.")

        return types.ServerResult(
            content=[
                types.TextContent(
                    type="text", text=f"Prompt '{prompt_name}' not found!"
                )
            ],
            isError=True,
        )

    async def _complete(self, req: types.CompleteRequest) -> types.ServerResult:
        """Execute a prompt completion on the relevant MCP server."""
        prompt_name = None
        client = None
        if hasattr(req.params.ref, 'name'):
            prompt_name = req.params.ref.name
            client = self.prompt_to_server.get(prompt_name)

        if client:
            try:
                ref = req.params.ref
                if hasattr(ref, 'name'):
                    _, original_name = self._split_key(ref.name)
                    ref = ref.model_copy(update={"name": original_name})
                result = await client.complete(ref, req.params.argument)
                return types.ServerResult(result)
            except Exception as e:
                self.logger.error(f"❌ Failed to complete prompt '{prompt_name}': {e}")
        else:
            self.logger.error(f"⚠️ Prompt '{prompt_name}' not found for completion.")

        return types.ServerResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"Prompt '{prompt_name}' not found for completion!",
                )
            ],
            isError=True,
        )

    ## Resources capabilities
    async def _list_resources(self, _: Any) -> types.ServerResult:
        """Aggregate resources from all remote MCP servers and return a combined list with namespacing."""
        all_resources = []
        for name, client in self.client_manager.clients.items():
            # Only call servers that support resources capability
            caps = self.capabilities.get(name)
            if not caps or not caps.resources:
                continue
            try:
                resources_result = await client.list_resources()
                # Namespace each resource using its name (or URI as fallback)
                for resource in resources_result.resources:
                    namespaced_resource = resource.model_copy()
                    resource_key = resource.name if resource.name else resource.uri
                    namespaced_resource.name = self._make_key(name, resource_key)
                    all_resources.append(namespaced_resource)
            except Exception as e:
                self.logger.error(f"Error fetching resources from {name}: {e}")

        return types.ServerResult(resources=all_resources)

    async def _read_resource(
        self, req: types.ReadResourceRequest
    ) -> types.ServerResult:
        """Read a resource from the appropriate backend MCP server."""
        resource_uri = req.params.uri
        client = self.resource_to_server.get(str(resource_uri))

        if client:
            try:
                result = await client.read_resource(req.params.uri)
                return types.ServerResult(result)
            except Exception as e:
                self.logger.error(f"❌ Failed to read resource '{resource_uri}': {e}")
        else:
            self.logger.error(f"⚠️ Resource '{resource_uri}' not found in any server.")

        return types.ServerResult(
            content=[
                types.TextContent(
                    type="text", text=f"Resource '{resource_uri}' not found!"
                )
            ],
            isError=True,
        )

    async def _subscribe_resource(
        self, req: types.SubscribeRequest
    ) -> types.ServerResult:
        """Subscribe to a resource for updates on a backend MCP server."""
        uri = req.params.uri
        client = self.resource_to_server.get(str(uri))

        if client:
            try:
                await client.subscribe_resource(uri)
                return types.ServerResult(types.EmptyResult())
            except Exception as e:
                self.logger.error(f"❌ Failed to subscribe to resource '{uri}': {e}")
        else:
            self.logger.error(f"⚠️ Resource '{uri}' not found for subscription.")

        return types.ServerResult(
            content=[
                types.TextContent(
                    type="text", text=f"Resource '{uri}' not found for subscription!"
                )
            ],
            isError=True,
        )

    async def _unsubscribe_resource(
        self, req: types.UnsubscribeRequest
    ) -> types.ServerResult:
        """Unsubscribe from a previously subscribed resource."""
        uri = req.params.uri
        client = self.resource_to_server.get(str(uri))

        if client:
            try:
                await client.unsubscribe_resource(uri)
                return types.ServerResult(types.EmptyResult())
            except Exception as e:
                self.logger.error(
                    f"❌ Failed to unsubscribe from resource '{uri}': {e}"
                )
        else:
            self.logger.error(f"⚠️ Resource '{uri}' not found for unsubscription.")

        return types.ServerResult(
            content=[
                types.TextContent(
                    type="text", text=f"Resource '{uri}' not found for unsubscription!"
                )
            ],
            isError=True,
        )

    # Utilization function
    async def _set_logging_level(
        self, req: types.SetLevelRequest
    ) -> types.ServerResult:
        """Broadcast a new logging level to all connected clients."""
        for client in self.client_manager.clients.values():
            try:
                await client.set_logging_level(req.params.level)
            except Exception as e:
                self.logger.error(f"❌ Failed to set logging level on client: {e}")

        return types.ServerResult(types.EmptyResult())

    async def _send_progress_notification(
        self, req: types.ProgressNotification
    ) -> None:
        """Relay a progress update to all backend clients."""
        for client in self.client_manager.clients.values():
            try:
                await client.send_progress_notification(
                    req.params.progressToken,
                    req.params.progress,
                    req.params.total,
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to send progress notification: {e}")

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

        self.notification_handlers[types.ProgressNotification] = (
            self._send_progress_notification
        )

        self.request_handlers[types.SetLevelRequest] = self._set_logging_level

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
        if tool_name in deny:
            return False
        allow = filter_config.get("allow", ["*"])
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
        """Reset tool mappings for a disconnected server and notify client."""
        async with self._register_lock:
            for key, mapping in self.tool_to_server.items():
                if mapping.server_name == server_name:
                    mapping.client = None
        await self._send_tools_list_changed()
        self.logger.info(f"🔄 Reset tool mappings for disconnected server '{server_name}'")

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

    async def run(
        self,
        read_stream,
        write_stream,
        initialization_options,
        raise_exceptions: bool = False,
    ):
        """Override run to capture the server session for notifications."""
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
