from contextlib import AsyncExitStack
from typing import Any, Dict, Optional, Set
import os
import asyncio
import time
import ipaddress
import socket
import urllib.parse


from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from src.utils.logger import get_logger


# Default allowlist for command execution
DEFAULT_ALLOWED_COMMANDS = {"node", "npx", "uvx", "python", "python3", "uv", "docker"}

# Env vars that cannot be overridden by server config
PROTECTED_ENV_VARS = {"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "HOME", "USER", "PYTHONPATH", "PYTHONHOME"}

# Private/internal IP ranges to block for SSRF
_PRIVATE_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _get_allowed_commands() -> set:
    """Return the set of allowed commands, from env var or default."""
    env_val = os.environ.get("MULTI_MCP_ALLOWED_COMMANDS", "")
    if env_val.strip():
        return {cmd.strip() for cmd in env_val.split(",") if cmd.strip()}
    return DEFAULT_ALLOWED_COMMANDS


def _validate_command(command: str) -> None:
    """Raise ValueError if command is not in the allowed list."""
    # Extract just the basename in case a full path is provided
    cmd_name = os.path.basename(command)
    allowed = _get_allowed_commands()
    if cmd_name not in allowed:
        raise ValueError(
            f"Command '{command}' is not in the allowed commands list. "
            f"Allowed: {sorted(allowed)}. "
            f"Set MULTI_MCP_ALLOWED_COMMANDS to override."
        )


def _validate_url(url: str) -> None:
    """Raise ValueError if URL is not safe (SSRF check)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme '{parsed.scheme}' is not allowed. Only http/https permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    # Resolve hostname to IP address(es) to prevent DNS rebinding
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname '{hostname}': {e}")

    for addrinfo in addrinfos:
        ip_str = addrinfo[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for private_range in _PRIVATE_RANGES:
            if ip in private_range:
                raise ValueError(
                    f"URL '{url}' resolves to private/internal IP '{ip}' which is not allowed."
                )


def _filter_env(env: dict) -> dict:
    """Remove protected env vars from the server-provided env dict."""
    return {k: v for k, v in env.items() if k not in PROTECTED_ENV_VARS}


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
        self._creation_locks: Dict[str, asyncio.Lock] = {}
        self.on_server_reconnected: Optional[Any] = None  # async callable(server_name, client)

    def _get_creation_lock(self, name: str) -> asyncio.Lock:
        """Get or create a per-server creation lock (lazily initialized)."""
        if name not in self._creation_locks:
            self._creation_locks[name] = asyncio.Lock()
        return self._creation_locks[name]

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
        Uses a per-server lock to prevent race conditions on concurrent first-access.

        Args:
            name (str): Server name

        Returns:
            ClientSession: Connected client session

        Raises:
            KeyError: If server is not found in clients or pending_configs
        """
        # Fast path: already connected (no lock needed)
        if name in self.clients:
            self.record_usage(name)
            return self.clients[name]

        # Slow path: acquire per-server lock before creating
        async with self._get_creation_lock(name):
            # Re-check after acquiring lock (another coroutine may have connected)
            if name in self.clients:
                self.record_usage(name)
                return self.clients[name]

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
                self.record_usage(name)
                return self.clients[name]

            raise KeyError(f"Unknown server: {name}")

    async def discover_all(
        self, config: "MultiMCPConfig"
    ) -> Dict[str, list]:
        """Connect to every server, fetch tool lists, disconnect lazy ones.

        stdio servers use AsyncExitStack (supports always_on keepalive).
        SSE servers use direct async-with blocks (required for anyio cancel scope compat).

        Returns:
            Dict mapping server_name -> list[types.Tool]
        """
        results: Dict[str, list] = {}

        for name, server_config in config.servers.items():
            server_dict = server_config.model_dump(exclude_none=True)
            command = server_dict.get("command")
            url = server_dict.get("url")

            if not command and not url:
                self.logger.warning(f"⚠️ Skipping '{name}': no command or URL")
                results[name] = []
                continue

            if url:
                # SSE: use direct async-with to stay within anyio's cancel scope rules
                results[name] = await self._discover_sse(name, url, server_config)
            else:
                # stdio: use AsyncExitStack so always_on servers can stay connected
                results[name] = await self._discover_stdio(name, server_dict, server_config)

        return results

    async def _discover_sse(self, name: str, url: str, server_config: "ServerConfig") -> list:
        """Discover tools from an HTTP/SSE server (anyio-compatible direct async-with).

        Tries Streamable HTTP (POST) first — the current MCP spec default.
        Falls back to legacy SSE (GET) if the server returns 405.
        """
        # Try Streamable HTTP (POST) first — newer spec, used by Exa and others
        try:
            async with streamable_http_client(url) as (read, write, _):
                async with ClientSession(read, write) as client:
                    init_result = await client.initialize()
                    tools = []
                    if init_result.capabilities.tools:
                        tools_result = await client.list_tools()
                        tools = tools_result.tools
                    self.logger.info(
                        f"🔌 Discovered {len(tools)} tools from '{name}' (streamable-http)"
                    )
                    return tools
        except Exception as e:
            self.logger.debug(f"Streamable HTTP failed for '{name}', trying SSE: {e}")

        # Fall back to legacy SSE (GET)
        try:
            async with sse_client(url=url) as (read, write):
                async with ClientSession(read, write) as client:
                    init_result = await client.initialize()
                    tools = []
                    if init_result.capabilities.tools:
                        tools_result = await client.list_tools()
                        tools = tools_result.tools
                    self.logger.info(
                        f"🔌 Discovered {len(tools)} tools from '{name}' (SSE)"
                    )
                    return tools
        except Exception as e:
            self.logger.error(f"❌ Discovery failed for '{name}': {e}")
            return []

    async def _discover_stdio(self, name: str, server_dict: dict, server_config: "ServerConfig") -> list:
        """Discover tools from a stdio server. Keeps always_on servers connected."""
        server_stack = AsyncExitStack()
        try:
            await server_stack.__aenter__()
            command = server_dict.get("command")
            args = server_dict.get("args", [])
            env = server_dict.get("env", {})
            safe_env = _filter_env(env)
            merged_env = os.environ.copy()
            merged_env.update(safe_env)

            params = StdioServerParameters(command=command, args=args, env=merged_env)
            read, write = await server_stack.enter_async_context(stdio_client(params))
            client = await server_stack.enter_async_context(ClientSession(read, write))

            init_result = await client.initialize()
            tools = []
            if init_result.capabilities.tools:
                tools_result = await client.list_tools()
                tools = tools_result.tools

            if not server_config.always_on:
                await server_stack.aclose()
                self.logger.info(
                    f"🔌 Discovered {len(tools)} tools from '{name}', disconnected (lazy)"
                )
            else:
                self.server_stacks[name] = server_stack
                self.clients[name] = client
                self.logger.info(
                    f"✅ Discovered {len(tools)} tools from '{name}', staying connected (always_on)"
                )
            return tools

        except Exception as e:
            self.logger.error(f"❌ Discovery failed for '{name}': {e}")
            try:
                await server_stack.aclose()
            except Exception:
                pass
            return []

    async def _connect_url_server(
        self,
        name: str,
        url: str,
        env: dict,
        server_stack: AsyncExitStack,
        server_config: Optional[Any] = None,
    ) -> ClientSession:
        """Connect to a URL-based MCP server using the correct transport.

        Respects server_config.type if set to 'sse' (skips Streamable HTTP).
        Otherwise tries Streamable HTTP first, falls back to legacy SSE.

        Uses a nested stack for the Streamable HTTP attempt so that a failed
        attempt is cleaned up safely before falling through to SSE.
        """
        transport_type = getattr(server_config, 'type', None) if server_config else None

        if transport_type != 'sse':
            # Try Streamable HTTP in a temporary nested stack for safe fallback
            fallback_stack = AsyncExitStack()
            try:
                await fallback_stack.__aenter__()
                read, write, _ = await fallback_stack.enter_async_context(
                    streamable_http_client(url)
                )
                client = await fallback_stack.enter_async_context(ClientSession(read, write))
                # Success: absorb the nested stack into the main server_stack for proper cleanup
                await server_stack.enter_async_context(fallback_stack)
                self.logger.info(f"🌐 Connected to '{name}' via Streamable HTTP")
                return client
            except Exception as e:
                await fallback_stack.aclose()
                self.logger.debug(f"Streamable HTTP failed for '{name}', trying SSE: {e}")

        # Use legacy SSE (fallback or explicit)
        read, write = await server_stack.enter_async_context(sse_client(url=url))
        client = await server_stack.enter_async_context(ClientSession(read, write))
        mode = "explicit" if transport_type == 'sse' else "fallback"
        self.logger.info(f"🌐 Connected to '{name}' via SSE ({mode})")
        return client

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
            # Clean up runtime state; keep tool_filters and idle_timeouts (config for reconnection)
            self.last_used.pop(name, None)
            self._creation_locks.pop(name, None)

    async def start_idle_checker(self, interval_seconds: float = 60.0) -> None:
        """Background task: periodically disconnect idle lazy servers."""
        while True:
            await asyncio.sleep(interval_seconds)
            await self._disconnect_idle_servers()

    async def start_always_on_watchdog(
        self, configs: Dict[str, dict], interval_seconds: float = 30.0
    ) -> None:
        """Background task: reconnect always_on servers if their connection drops."""
        while True:
            await asyncio.sleep(interval_seconds)
            for name in list(self.always_on_servers):
                if name not in self.clients:
                    self.logger.warning(f"⚠️ Always-on server '{name}' disconnected — reconnecting...")
                    server_config = configs.get(name)
                    if not server_config:
                        continue
                    try:
                        server_stack = AsyncExitStack()
                        await server_stack.__aenter__()
                        command = server_config.get("command")
                        url = server_config.get("url")
                        args = server_config.get("args", [])
                        env = server_config.get("env", {})
                        safe_env = _filter_env(env)
                        merged_env = os.environ.copy()
                        merged_env.update(safe_env)

                        if command:
                            params = StdioServerParameters(command=command, args=args, env=merged_env)
                            read, write = await server_stack.enter_async_context(stdio_client(params))
                            client = await server_stack.enter_async_context(ClientSession(read, write))
                        elif url:
                            client = await self._connect_url_server(name, url, env, server_stack)
                        else:
                            await server_stack.aclose()
                            continue

                        await client.initialize()
                        self.clients[name] = client
                        self.server_stacks[name] = server_stack
                        self.logger.info(f"✅ Reconnected always-on server '{name}'")

                        # Notify proxy so it can update tool mappings
                        if self.on_server_reconnected:
                            try:
                                await self.on_server_reconnected(name, client)
                            except Exception as cb_err:
                                self.logger.warning(f"⚠️ on_server_reconnected callback failed for '{name}': {cb_err}")
                    except Exception as e:
                        self.logger.error(f"❌ Failed to reconnect '{name}': {e}")
                        try:
                            await server_stack.aclose()
                        except Exception:
                            pass

    async def _create_single_client(self, name: str, server: dict) -> None:
        """
        Internal helper to create a single client from config.
        Uses a per-server AsyncExitStack so a crashed client cannot
        propagate exceptions into the shared server lifecycle.

        Args:
            name (str): Server name
            server (dict): Server configuration
        """
        server_stack = AsyncExitStack()
        await server_stack.__aenter__()

        try:
            command = server.get("command")
            url = server.get("url")
            args = server.get("args", [])
            env = server.get("env", {})

            if command:
                _validate_command(command)
                safe_env = _filter_env(env)
                merged_env = os.environ.copy()
                merged_env.update(safe_env)
                self.logger.info(f"🔌 Creating stdio client for {name}")
                params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=merged_env,
                )
                read, write = await server_stack.enter_async_context(stdio_client(params))
                session = await server_stack.enter_async_context(
                    ClientSession(read, write)
                )

            elif url:
                _validate_url(url)
                session = await self._connect_url_server(name, url, env, server_stack)

            else:
                self.logger.warning(f"⚠️ Skipping {name}: No command or URL provided.")
                await server_stack.aclose()
                return

            self.clients[name] = session
            self.server_stacks[name] = server_stack
            self.logger.info(f"✅ Connected to {name}")

        except Exception as e:
            self.logger.error(f"❌ Failed to create client for {name}: {e}")
            try:
                await server_stack.aclose()
            except Exception:
                pass
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
