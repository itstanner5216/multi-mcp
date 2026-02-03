from contextlib import AsyncExitStack
from typing import Dict, Optional
import os
import asyncio

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
        self.pending_configs: Dict[str, dict] = {}
        self._connection_semaphore = asyncio.Semaphore(max_concurrent_connections)
        self._connection_timeout = connection_timeout
        self.logger = get_logger("multi_mcp.ClientManager")

    def add_pending_server(self, name: str, config: dict) -> None:
        """
        Add a server configuration to the pending registry without connecting.

        Args:
            name (str): Server name
            config (dict): Server configuration (command/url, args, env, etc.)
        """
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
