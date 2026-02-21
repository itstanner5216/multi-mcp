import asyncio
import os
import uvicorn
import json
from pathlib import Path
from typing import Literal, Any, Optional
from pydantic_settings import BaseSettings

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
    config: str = "./mcp.json"
    api_key: Optional[str] = None  # API key for authentication (env: MULTI_MCP_API_KEY)

    class Config:
        env_prefix = "MULTI_MCP_"


class MultiMCP:
    def __init__(self, **settings: Any):
        self.settings = MCPSettings(**settings)
        configure_logging(level=self.settings.log_level)
        self.logger = get_logger("MultiMCP")
        self.proxy: Optional[MCPProxyServer] = None
        self.client_manager = MCPClientManager()

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
        """Connect to all servers from JSON config, discover tools, write YAML."""
        config = MultiMCPConfig()
        json_config = self.load_mcp_config(path=self.settings.config) or {}
        json_servers = json_config.get("mcpServers", {})

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

    async def run(self):
        """Entry point to run the MultiMCP server: loads config, initializes clients, starts server."""
        self.logger.info(
            f"🚀 Starting MultiMCP with transport: {self.settings.transport}"
        )
        await self._bootstrap_from_yaml(YAML_CONFIG_PATH)

        config = self.load_mcp_config(path=self.settings.config)
        if not config:
            self.logger.error("❌ Failed to load MCP config.")
            return
        clients = await self.client_manager.create_clients(config)
        if not clients:
            self.logger.error("❌ No valid clients were created.")
            return

        self.logger.info(f"✅ Connected clients: {list(clients.keys())}")

        asyncio.create_task(self.client_manager.start_idle_checker())

        try:
            self.proxy = await MCPProxyServer.create(self.client_manager)

            await self.start_server()
        finally:
            await self.client_manager.close()

    def load_mcp_config(self, path="./mcp.json"):
        """Loads MCP JSON configuration From File."""
        if not os.path.exists(path):
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

            # Count pending servers (Task 05 will add pending_configs)
            # Use getattr to gracefully handle absence of pending_configs
            pending_configs = getattr(self.proxy.client_manager, "pending_configs", {})
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
