from contextlib import AsyncExitStack
from typing import Dict, Optional, Set
import os
import asyncio
import time


from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from langchain_mcp_adapters.client import (
    DEFAULT_ENCODING,
    DEFAULT_ENCODING_ERROR_HANDLER,
)
from src.utils.logger import get_logger


class MCPClientManager:
    """
    Manages the lifecycle of multiple MCP clients (either stdio or SSE).
    Handles creation, storage, and graceful cleanup of client sessions.
    Supports lazy loading via pending_configs registry.
    """

    def __init__(
        self, max_concurrent_connections: int = 10, connection_timeout: float = 30.0
    ):
        self.stack = AsyncExitStack()
        self.clients: Dict[str, ClientSession] = {}
        self.server_stacks: Dict[str, AsyncExitStack] = {}
        self.pending_configs: Dict[str, dict] = {}
        self.tool_filters: Dict[str, Optional[dict]] = {}
        self._connection_semaphore = asyncio.Semaphore(max_concurrent_connections)
        self._connection_timeout = connection_timeout
        self.logger = get_logger("multi_mcp.ClientManager")
        self.always_on_servers: Set[str] = set()
        self.idle_timeouts: Dict[str, float] = {}   # server_name -> seconds
        self.last_used: Dict[str, float] = {}        # server_name -> monotonic timestamp

    def _parse_tool_filter(self, config: dict) -> Optional[dict]:
        """Normalize the 'tools' field from a server config into {allow, deny} format.

        Supports:
          "tools": ["tool_a", "tool_b"]          -> allow list shorthand
          "tools": {"allow": [...], "deny": [...]} -> full format
          absent / null                            -> no filtering (all tools allowed)
        """
        tools = config.get("tools")
        if tools is None:
            return None
        if isinstance(tools, list):
            return {"allow": tools, "deny": []}
        if isinstance(tools, dict):
            return {
                "allow": tools.get("allow", ["*"]),
                "deny": tools.get("deny", []),
            }
        return None

    def add_pending_server(self, name: str, config: dict) -> None:
        """
        Add a server configuration to the pending registry without connecting.

        Args:
            name (str): Server name
            config (dict): Server configuration (command/url, args, env, etc.)
        """
        self.tool_filters[name] = self._parse_tool_filter(config)
        self.pending_configs[name] = config
        self.logger.info(f"📋 Added pending server: {name}")

    async def get_or_create_client(self, name: str) -> ClientSession:
        """
        Get an existing client or create it from pending configs on first access.

        Args:
            name (str): Server name

        Returns:
            ClientSession: Connected client session

        Raises:
            KeyError: If server is not found in clients or pending_configs
        """
        # Return existing client if already connected
        if name in self.clients:
            return self.clients[name]

        # Create from pending config if available
        if name in self.pending_configs:
            config = self.pending_configs.pop(name)
            async with self._connection_semaphore:
                try:
                    await asyncio.wait_for(
                        self._create_single_client(name, config),
                        timeout=self._connection_timeout,
                    )
                except asyncio.TimeoutError:
                    self.logger.error(f"❌ Connection timeout for {name}")
                    raise
            return self.clients[name]

        raise KeyError(f"Unknown server: {name}")

    async def discover_all(
        self, config: "MultiMCPConfig"
    ) -> Dict[str, list]:
        """Connect to every server, fetch tool lists, disconnect lazy ones.

        Uses per-server AsyncExitStack so lazy servers can be properly closed
        (not just removed from the clients dict).

        Returns:
            Dict mapping server_name -> list[types.Tool]
        """
        results: Dict[str, list] = {}

        for name, server_config in config.servers.items():
            server_stack = AsyncExitStack()
            try:
                await server_stack.__aenter__()
                server_dict = server_config.model_dump(exclude_none=True)

                command = server_dict.get("command")
                url = server_dict.get("url")
                args = server_dict.get("args", [])
                env = server_dict.get("env", {})
                merged_env = os.environ.copy()
                merged_env.update(env)

                if command:
                    from mcp.client.stdio import StdioServerParameters, stdio_client
                    params = StdioServerParameters(command=command, args=args, env=merged_env)
                    read, write = await server_stack.enter_async_context(stdio_client(params))
                elif url:
                    from mcp.client.sse import sse_client
                    read, write = await server_stack.enter_async_context(sse_client(url=url))
                else:
                    self.logger.warning(f"⚠️ Skipping '{name}': no command or URL")
                    await server_stack.aclose()
                    results[name] = []
                    continue

                from mcp.client.session import ClientSession
                client = await server_stack.enter_async_context(ClientSession(read, write))

                init_result = await client.initialize()
                tools = []
                if init_result.capabilities.tools:
                    tools_result = await client.list_tools()
                    tools = tools_result.tools

                results[name] = tools

                if not server_config.always_on:
                    # Properly close the connection — subprocess terminated, socket closed
                    await server_stack.aclose()
                    self.logger.info(
                        f"🔌 Discovered {len(tools)} tools from '{name}', disconnected (lazy)"
                    )
                else:
                    # Keep always_on server alive — store stack and client
                    self.server_stacks[name] = server_stack
                    self.clients[name] = client
                    self.logger.info(
                        f"✅ Discovered {len(tools)} tools from '{name}', staying connected (always_on)"
                    )

            except Exception as e:
                self.logger.error(f"❌ Discovery failed for '{name}': {e}")
                try:
                    await server_stack.aclose()
                except Exception:
                    pass
                results[name] = []

        return results

    def record_usage(self, server_name: str) -> None:
        """Update last-used timestamp for a server."""
        self.last_used[server_name] = time.monotonic()

    async def _disconnect_idle_servers(self) -> None:
        """Disconnect lazy servers that have exceeded their idle timeout."""
        now = time.monotonic()
        to_disconnect = [
            name for name in list(self.clients.keys())
            if name not in self.always_on_servers
            and name in self.idle_timeouts
            and now - self.last_used.get(name, 0) > self.idle_timeouts[name]
        ]
        for name in to_disconnect:
            self.logger.info(f"💤 Disconnecting idle server: {name}")
            del self.clients[name]
            # Close the server stack if it exists
            stack = self.server_stacks.pop(name, None)
            if stack:
                try:
                    await stack.aclose()
                except Exception as e:
                    self.logger.warning(f"⚠️ Error closing stack for '{name}': {e}")

    async def start_idle_checker(self, interval_seconds: float = 60.0) -> None:
        """Background task: periodically disconnect idle lazy servers."""
        while True:
            await asyncio.sleep(interval_seconds)
            await self._disconnect_idle_servers()

    async def _create_single_client(self, name: str, server: dict) -> None:
        """
        Internal helper to create a single client from config.

        Args:
            name (str): Server name
            server (dict): Server configuration
        """
        # Ensure stack is initialized
        if not hasattr(self.stack, "_exit_callbacks"):
            await self.stack.__aenter__()

        try:
            command = server.get("command")
            url = server.get("url")
            args = server.get("args", [])
            env = server.get("env", {})
            encoding = server.get("encoding", DEFAULT_ENCODING)
            encoding_error_handler = server.get(
                "encoding_error_handler", DEFAULT_ENCODING_ERROR_HANDLER
            )

            merged_env = os.environ.copy()
            merged_env.update(env)

            if command:
                self.logger.info(f"🔌 Creating stdio client for {name}")
                params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=merged_env,
                    encoding=encoding,
                    encoding_error_handler=encoding_error_handler,
                )
                read, write = await self.stack.enter_async_context(stdio_client(params))
                session = await self.stack.enter_async_context(
                    ClientSession(read, write)
                )

            elif url:
                self.logger.info(f"🌐 Creating SSE client for {name}")
                read, write = await self.stack.enter_async_context(sse_client(url=url))
                session = await self.stack.enter_async_context(
                    ClientSession(read, write)
                )

            else:
                self.logger.warning(f"⚠️ Skipping {name}: No command or URL provided.")
                return

            self.clients[name] = session
            self.logger.info(f"✅ Connected to {name}")

        except Exception as e:
            self.logger.error(f"❌ Failed to create client for {name}: {e}")
            raise

    async def create_clients(
        self, config: dict, lazy: bool = False
    ) -> Dict[str, ClientSession]:
        """
        Creates MCP clients defined in the given config.
        Supports both stdio and SSE transport.

        Args:
            config (dict): Configuration dictionary with "mcpServers" mapping
                           server names to their connection parameters.
            lazy (bool): If True, store configs without connecting (default: False).

        Returns:
            Dict[str, ClientSession]: Dictionary mapping server names to live ClientSession objects.
                                     Empty dict if lazy=True.
        """
        if lazy:
            # Store all configs as pending without connecting
            for name, server in config.get("mcpServers", {}).items():
                self.add_pending_server(name, server)
            return {}

        # Eager mode: connect immediately (existing behavior)
        await self.stack.__aenter__()  # manually enter the stack once

        for name, server in config.get("mcpServers", {}).items():
            self.tool_filters[name] = self._parse_tool_filter(server)
            if name in self.clients:
                self.logger.warning(
                    f"⚠️ Client '{name}' already exists and will be overridden."
                )
            await self._create_single_client(name, server)

        return self.clients

    def get_client(self, name: str) -> Optional[ClientSession]:
        """
        Retrieves an existing client by name.

        Args:
            name (str): The name of the client (as defined in config).

        Returns:
            Optional[ClientSession]: The ClientSession object, or None if not found.
        """
        return self.clients.get(name)

    async def close(self) -> None:
        """
        Closes all clients and releases resources managed by the async context stack.
        """
        await self.stack.aclose()
