import asyncio
import os
import uvicorn
import json
from pathlib import Path
from typing import Literal, Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.stdio import stdio_server
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.sse import SseServerTransport

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer
from src.multimcp.yaml_config import load_config, save_config, MultiMCPConfig, ServerConfig
from src.multimcp.cache_manager import merge_discovered_tools, get_enabled_tools
from src.utils.logger import configure_logging, get_logger

YAML_CONFIG_PATH = Path.home() / ".config" / "multi-mcp" / "servers.yaml"


class MCPSettings(BaseSettings):
    """Configuration settings for the MultiMCP server."""

    host: str = "127.0.0.1"
    port: int = 8085
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    transport: Literal["stdio", "sse"] = "stdio"
    sse_server_debug: bool = False
    config: Optional[str] = None
    api_key: Optional[str] = None  # API key for authentication (env: MULTI_MCP_API_KEY)

    model_config = SettingsConfigDict(env_prefix="MULTI_MCP_")


class MultiMCP:
    def __init__(self, **settings: Any):
        self.settings = MCPSettings(**settings)
        configure_logging(level=self.settings.log_level)
        self.logger = get_logger("MultiMCP")
        self.proxy: Optional[MCPProxyServer] = None
        self.client_manager = MCPClientManager()
        self._bg_tasks: list[asyncio.Task] = []

    def _track_task(self, coro, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.append(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task in self._bg_tasks:
            self._bg_tasks.remove(task)
        if not task.cancelled() and task.exception():
            self.logger.error(f"❌ Background task '{task.get_name()}' failed: {task.exception()}")

    @property
    def auth_enabled(self) -> bool:
        """Check if API key authentication is enabled."""
        return self.settings.api_key is not None and len(self.settings.api_key) > 0

    async def _bootstrap_from_yaml(self, yaml_path: Path) -> MultiMCPConfig:
        """Load YAML config or run first-time discovery. Apply settings to client_manager."""
        config = load_config(yaml_path)

        if not config.servers:
            self.logger.info("No YAML config found — running first-time discovery...")
            config = await self._first_run_discovery(yaml_path)
        else:
            self.logger.info(f"Loaded config from {yaml_path}")
            # Merge any new servers from JSON that aren't in YAML yet
            new_servers = self._find_new_json_servers(config)
            if new_servers:
                self.logger.info(f"🔍 Found {len(new_servers)} new server(s) in JSON config: {', '.join(new_servers)}")
                config = await self._discover_new_servers(config, new_servers, yaml_path)

        # Apply tool filters, idle timeouts, and always_on settings
        for server_name, server_config in config.servers.items():
            enabled = get_enabled_tools(config, server_name)
            if enabled:
                self.client_manager.tool_filters[server_name] = {
                    "allow": list(enabled), "deny": []
                }
            self.client_manager.idle_timeouts[server_name] = (
                server_config.idle_timeout_minutes * 60
            )
            if server_config.always_on:
                self.client_manager.always_on_servers.add(server_name)

        return config

    async def _first_run_discovery(self, yaml_path: Path) -> MultiMCPConfig:
        """Connect to all servers from JSON/plugin config, discover tools, write YAML."""
        config = MultiMCPConfig()

        # Gather servers from JSON config (if provided) and Claude plugins
        json_servers: dict[str, dict] = {}
        if self.settings.config:
            json_config = self.load_mcp_config(path=self.settings.config) or {}
            json_servers.update(self._extract_mcp_servers(json_config))
        plugin_servers = self._scan_claude_plugins()
        if plugin_servers:
            self.logger.info(f"🔌 Found {len(plugin_servers)} server(s) from Claude plugins")
            # Don't overwrite JSON-defined servers with plugin versions
            for name, srv in plugin_servers.items():
                if name not in json_servers:
                    json_servers[name] = srv

        for name, srv in json_servers.items():
            valid_fields = ServerConfig.model_fields.keys()
            filtered = {k: v for k, v in srv.items() if k in valid_fields}
            ignored = set(srv.keys()) - set(filtered.keys())
            if ignored:
                self.logger.warning(f"⚠️ '{name}': ignoring unknown config keys: {ignored}")
            config.servers[name] = ServerConfig(**filtered)

        discovered = await self.client_manager.discover_all(config)
        for server_name, tools in discovered.items():
            merge_discovered_tools(config, server_name, tools)

        save_config(config, yaml_path)
        self.logger.info(f"Wrote initial config to {yaml_path}")
        return config

    @staticmethod
    def _extract_mcp_servers(data: dict) -> dict[str, dict]:
        """Extract MCP server entries from various config formats.

        Supports:
          - { "mcpServers": { ... } }  (Claude Desktop, Copilot CLI, OpenCode)
          - { "servers": { ... } }     (VSCode)
          - { "mcp": { ... } }         (Gemini/OpenCode alternate)
          - { "name": { "command": ..., "args": ... } }  (Claude plugin .mcp.json)
        """
        for key in ("mcpServers", "servers", "mcp"):
            section = data.get(key)
            if isinstance(section, dict) and section:
                return MultiMCP._normalize_server_entries(section)

        # Bare format: every top-level key is a server name (Claude plugins)
        if all(isinstance(v, dict) for v in data.values()) and data:
            # Verify at least one entry looks like a server config
            server_keys = {"command", "args", "url", "type"}
            if any(server_keys & set(v.keys()) for v in data.values()):
                return MultiMCP._normalize_server_entries(data)
        return {}

    @staticmethod
    def _normalize_server_entries(section: dict) -> dict[str, dict]:
        """Normalize server entries: handle command-as-list, filter non-dicts."""
        normalized = {}
        for name, srv in section.items():
            if not isinstance(srv, dict):
                continue
            if "command" in srv and isinstance(srv["command"], list):
                cmd_list = srv["command"]
                if cmd_list:
                    srv = {**srv, "command": cmd_list[0], "args": cmd_list[1:]}
                else:
                    continue  # Skip entries with empty command list
            normalized[name] = srv
        return normalized

    def _scan_claude_plugins(self) -> dict[str, dict]:
        """Scan Claude Code plugin cache for active MCP server configs."""
        plugins_dir = Path.home() / ".claude" / "plugins" / "cache"
        settings_path = Path.home() / ".claude" / "settings.local.json"
        if not plugins_dir.exists():
            return {}

        # Load disabled plugins from Claude settings
        # Plugins not listed are treated as enabled (Claude default behavior)
        disabled_plugins: set[str] = set()
        if settings_path.exists():
            try:
                with open(settings_path) as f:
                    settings = json.load(f)
                for plugin_id, is_enabled in settings.get("enabledPlugins", {}).items():
                    if not is_enabled:
                        disabled_plugins.add(plugin_id)
            except (json.JSONDecodeError, OSError):
                pass

        servers: dict[str, dict] = {}
        for mcp_json in plugins_dir.rglob(".mcp.json"):
            plugin_dir = mcp_json.parent
            # Skip orphaned (old) plugin versions
            if (plugin_dir / ".orphaned_at").exists():
                continue
            # Check if plugin is enabled in Claude settings
            # Plugin path: .../cache/{source}/{name}/{version}/
            parts = plugin_dir.relative_to(plugins_dir).parts
            if len(parts) >= 2:
                plugin_id = f"{parts[1]}@{parts[0]}"
                if plugin_id in disabled_plugins:
                    continue
            try:
                with open(mcp_json) as f:
                    data = json.load(f)
                extracted = self._extract_mcp_servers(data)
                if extracted:
                    servers.update(extracted)
            except (json.JSONDecodeError, OSError):
                continue
        return servers

    def _find_new_json_servers(self, config: MultiMCPConfig) -> dict:
        """Return server configs not already in YAML.

        Priority:
        1. mcp.json exists → sole source (no auto-discovery)
        2. Otherwise → scan config.sources paths + Claude plugin cache
        """
        all_json_servers: dict[str, dict] = {}

        if self.settings.config and os.path.exists(self.settings.config):
            # Dedicated mcp.json exists — use only that
            json_config = self.load_mcp_config(path=self.settings.config) or {}
            all_json_servers.update(self._extract_mcp_servers(json_config))
        else:
            # Auto-discover from configured sources
            if config.sources:
                MCP_CONFIG_NAMES = [
                    "mcp.json", ".mcp.json", "mcp-config.json",
                    "mcp_config.json", "claude_desktop_config.json",
                ]
                for source_path in config.sources:
                    expanded = os.path.expanduser(source_path)
                    if not os.path.exists(expanded):
                        self.logger.warning(f"⚠️ Source path not found: {expanded}")
                        continue
                    files_to_check = []
                    if os.path.isdir(expanded):
                        for name in MCP_CONFIG_NAMES:
                            candidate = os.path.join(expanded, name)
                            if os.path.isfile(candidate):
                                files_to_check.append(candidate)
                    else:
                        files_to_check.append(expanded)
                    for filepath in files_to_check:
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            servers = self._extract_mcp_servers(data)
                            if servers:
                                self.logger.info(f"📂 Found {len(servers)} server(s) in {filepath}")
                                all_json_servers.update(servers)
                        except (json.JSONDecodeError, OSError) as e:
                            self.logger.warning(f"⚠️ Failed to read source {filepath}: {e}")

            # Always scan Claude plugin cache
            plugin_servers = self._scan_claude_plugins()
            if plugin_servers:
                self.logger.info(f"🔌 Found {len(plugin_servers)} server(s) from Claude plugins")
                for name, srv in plugin_servers.items():
                    if name not in all_json_servers:
                        all_json_servers[name] = srv

        new_servers = {}
        for name, srv in all_json_servers.items():
            if name not in config.servers:
                valid_fields = ServerConfig.model_fields.keys()
                filtered = {k: v for k, v in srv.items() if k in valid_fields}
                ignored = set(srv.keys()) - set(filtered.keys())
                if ignored:
                    self.logger.warning(f"⚠️ '{name}': ignoring unknown config keys: {ignored}")
                new_servers[name] = ServerConfig(**filtered)
        return new_servers

    async def _discover_new_servers(
        self, config: MultiMCPConfig, new_servers: dict, yaml_path: Path
    ) -> MultiMCPConfig:
        """Discover tools from new servers and merge them into existing config."""
        # Add new servers to config for discovery
        discovery_config = MultiMCPConfig(servers=new_servers)
        for name, srv in new_servers.items():
            config.servers[name] = srv

        discovered = await self.client_manager.discover_all(discovery_config)
        for server_name, tools in discovered.items():
            merge_discovered_tools(config, server_name, tools)

        save_config(config, yaml_path)
        self.logger.info(f"📝 Updated config with new servers at {yaml_path}")
        return config

    async def run(self):
        """Entry point to run the MultiMCP server: loads config, initializes clients, starts server."""
        self.logger.info(
            f"🚀 Starting MultiMCP with transport: {self.settings.transport}"
        )
        yaml_config = await self._bootstrap_from_yaml(YAML_CONFIG_PATH)

        # Register ALL servers as pending — proxy starts instantly from YAML cache
        for server_name, server_config in yaml_config.servers.items():
            server_dict = server_config.model_dump(exclude_none=True)
            self.client_manager.add_pending_server(server_name, server_dict)

        # Start idle checker background task
        self._track_task(self.client_manager.start_idle_checker(), "idle-checker")

        # Build config dict for watchdog reconnects
        always_on_configs = {
            name: srv.model_dump(exclude_none=True)
            for name, srv in yaml_config.servers.items()
            if srv.always_on
        }
        self._track_task(self.client_manager.start_always_on_watchdog(always_on_configs), "always-on-watchdog")

        # Background: connect always_on servers after proxy starts
        async def _connect_always_on() -> None:
            for server_name, server_config in yaml_config.servers.items():
                if not server_config.always_on:
                    continue
                try:
                    client = await self.client_manager.get_or_create_client(server_name)
                    if self.proxy:
                        await self.proxy.initialize_single_client(server_name, client)
                        await self.proxy._send_tools_list_changed()
                        self.logger.info(f"✅ Always-on server '{server_name}' connected")
                except Exception as e:
                    self.logger.warning(f"⚠️ Always-on '{server_name}' failed to connect: {e}")

        try:
            self.proxy = await MCPProxyServer.create(self.client_manager)
            self.client_manager._on_server_disconnected = self.proxy._on_server_disconnected

            # Pre-populate tool list from YAML cache so tools are visible immediately
            self.proxy.load_tools_from_yaml(yaml_config)

            # Connect always_on servers in background (don't block startup)
            self._track_task(_connect_always_on(), "connect-always-on")

            await self.start_server()
        finally:
            for task in list(self._bg_tasks):
                task.cancel()
            await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)
            await self.client_manager.close()

    def load_mcp_config(self, path=None):
        """Loads MCP JSON configuration From File."""
        if not path or not os.path.exists(path):
            self.logger.error(f"❌ Config file does not exist: {path}")
            return None

        with open(path, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
                return data
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Error parsing JSON config: {e}")
                return None

    def _check_auth(self, request: Request) -> Optional[JSONResponse]:
        """
        Check if request is authenticated.

        Returns None if authenticated, JSONResponse with 401 if not.
        """
        if not self.auth_enabled:
            return None  # Auth disabled, allow request

        # For SSE endpoint, check query parameter
        if request.url.path == "/sse":
            token = request.query_params.get("token")
            if token == self.settings.api_key:
                return None  # Valid token
            return JSONResponse(
                {"error": "Unauthorized: Invalid or missing token"}, status_code=401
            )

        # For HTTP endpoints, check Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                {"error": "Unauthorized: Missing Authorization header"}, status_code=401
            )

        # Check Bearer token format
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {
                    "error": "Unauthorized: Invalid Authorization format (expected 'Bearer <token>')"
                },
                status_code=401,
            )

        token = auth_header[7:]  # Remove "Bearer " prefix
        if token == self.settings.api_key:
            return None  # Valid token

        return JSONResponse({"error": "Unauthorized: Invalid API key"}, status_code=401)

    async def _auth_wrapper(self, handler, request: Request):
        """Wrapper to apply authentication check to endpoint handlers."""
        auth_error = self._check_auth(request)
        if auth_error:
            return auth_error
        return await handler(request)

    async def start_server(self):
        """Start the proxy server in stdio or SSE mode."""
        if self.settings.transport == "stdio":
            await self.start_stdio_server()
        elif self.settings.transport == "sse":
            await self.start_sse_server()
        else:
            raise ValueError(f"Unsupported transport: {self.settings.transport}")

    async def start_stdio_server(self) -> None:
        """Run the proxy server over stdio."""
        async with stdio_server() as (read_stream, write_stream):
            await self.proxy.run(
                read_stream,
                write_stream,
                self.proxy.create_initialization_options(),
            )

    def create_starlette_app(self) -> Starlette:
        """Create Starlette app with routes and optional auth middleware."""
        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            # Check auth for SSE endpoint
            auth_error = self._check_auth(request)
            if auth_error:
                return auth_error

            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await self.proxy.run(
                    streams[0],
                    streams[1],
                    self.proxy.create_initialization_options(),
                )

        # Wrap HTTP endpoints with auth
        async def auth_mcp_servers(request):
            return await self._auth_wrapper(self.handle_mcp_servers, request)

        async def auth_mcp_tools(request):
            return await self._auth_wrapper(self.handle_mcp_tools, request)

        async def auth_health(request):
            return await self._auth_wrapper(self.handle_health, request)

        async def auth_mcp_control(request):
            return await self._auth_wrapper(self.handle_mcp_control, request)

        starlette_app = Starlette(
            debug=self.settings.sse_server_debug,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
                # Dynamic endpoints with auth
                Route(
                    "/mcp_servers",
                    endpoint=auth_mcp_servers,
                    methods=["GET", "POST"],
                ),
                Route(
                    "/mcp_servers/{name}",
                    endpoint=auth_mcp_servers,
                    methods=["DELETE"],
                ),
                Route("/mcp_tools", endpoint=auth_mcp_tools, methods=["GET"]),
                Route("/health", endpoint=auth_health, methods=["GET"]),
                Route("/mcp_control", endpoint=auth_mcp_control, methods=["POST"]),
            ],
        )

        return starlette_app

    async def start_sse_server(self) -> None:
        """Run the proxy server over SSE transport."""
        starlette_app = self.create_starlette_app()

        config = uvicorn.Config(
            starlette_app,
            host=self.settings.host,
            port=self.settings.port,
            log_level=self.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def handle_mcp_servers(self, request: Request) -> JSONResponse:
        """Handle GET/POST/DELETE to list, add, or remove MCP clients at runtime."""
        method = request.method

        if method == "GET":
            servers = list(self.proxy.client_manager.clients.keys())
            return JSONResponse({"active_servers": servers})

        elif method == "POST":
            try:
                payload = await request.json()

                if "mcpServers" not in payload:
                    return JSONResponse(
                        {"error": "Missing 'mcpServers' in payload"}, status_code=400
                    )

                # Create clients from full `mcpServers` dict
                new_clients = await self.proxy.client_manager.create_clients(payload)

                if not new_clients:
                    return JSONResponse(
                        {"error": "No clients were created"}, status_code=500
                    )

                for name, client in new_clients.items():
                    await self.proxy.register_client(name, client)

                return JSONResponse({"message": f"Added {list(new_clients.keys())}"})

            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        elif method == "DELETE":
            name = request.path_params.get("name")
            if not name:
                return JSONResponse(
                    {"error": "Missing client name in path"}, status_code=400
                )

            client = self.proxy.client_manager.clients.get(name)
            if not client:
                return JSONResponse(
                    {"error": f"No client named '{name}'"}, status_code=404
                )

            try:
                await self.proxy.unregister_client(name)
                return JSONResponse(
                    {"message": f"Client '{name}' removed successfully"}
                )
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        return JSONResponse({"error": f"Unsupported method: {method}"}, status_code=405)

    async def handle_mcp_tools(self, request: Request) -> JSONResponse:
        """Return the list of currently available tools grouped by server."""
        try:
            if not self.proxy:
                return JSONResponse({"error": "Proxy not initialized"}, status_code=500)

            tools_by_server = {}
            for server_name, client in self.proxy.client_manager.clients.items():
                try:
                    tools = await client.list_tools()
                    tools_by_server[server_name] = [tool.name for tool in tools.tools]
                except Exception as e:
                    tools_by_server[server_name] = f"❌ Error: {str(e)}"

            return JSONResponse({"tools": tools_by_server})

        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def handle_health(self, request: Request) -> JSONResponse:
        """Return health status with connected and pending server counts."""
        try:
            if not self.proxy:
                return JSONResponse(
                    {"status": "unavailable", "error": "Proxy not initialized"},
                    status_code=503,
                )

            # Count connected servers
            connected_count = len(self.proxy.client_manager.clients)

            pending_configs = self.proxy.client_manager.pending_configs
            pending_count = len(pending_configs)

            return JSONResponse(
                {
                    "status": "healthy",
                    "connected_servers": connected_count,
                    "pending_servers": pending_count,
                }
            )

        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def handle_mcp_control(self, request: Request) -> JSONResponse:
        """Handle POST /mcp_control for manual server enable/disable."""
        try:
            payload = await request.json()

            action = payload.get("action")
            server_name = payload.get("server")

            if not action or not server_name:
                return JSONResponse(
                    {"error": "Missing 'action' or 'server' in payload"},
                    status_code=400,
                )

            if action == "enable":
                # Check if server is already active
                if server_name in self.proxy.client_manager.clients:
                    return JSONResponse(
                        {"message": f"Server '{server_name}' already active"},
                        status_code=200,
                    )

                # Check if server exists in pending configs
                if server_name not in self.proxy.client_manager.pending_configs:
                    return JSONResponse(
                        {
                            "error": f"Server '{server_name}' not found in pending configs"
                        },
                        status_code=404,
                    )

                # Enable the server
                try:
                    client = await self.proxy.client_manager.get_or_create_client(
                        server_name
                    )
                    await self.proxy.register_client(server_name, client)

                    return JSONResponse(
                        {"message": f"Server '{server_name}' enabled successfully"}
                    )
                except Exception as e:
                    return JSONResponse(
                        {"error": f"Failed to enable server: {str(e)}"}, status_code=500
                    )

            elif action == "disable":
                # Check if server is active
                if server_name not in self.proxy.client_manager.clients:
                    return JSONResponse(
                        {"error": f"Server '{server_name}' not active"}, status_code=404
                    )

                # Disable (soft unload - move to pending without removing config)
                try:
                    # Get the server config before unregistering
                    # For now, we'll just unregister. Full disable logic would store config
                    await self.proxy.unregister_client(server_name)

                    return JSONResponse(
                        {"message": f"Server '{server_name}' disabled successfully"}
                    )
                except Exception as e:
                    return JSONResponse(
                        {"error": f"Failed to disable server: {str(e)}"},
                        status_code=500,
                    )

            else:
                return JSONResponse(
                    {"error": f"Invalid action: {action}. Use 'enable' or 'disable'"},
                    status_code=400,
                )

        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
