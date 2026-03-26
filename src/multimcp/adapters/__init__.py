"""multimcp.adapters — static per-tool MCP config read/write adapters.

All 16 tool adapters are available through the registry:

    from src.multimcp.adapters import get_adapter, list_adapters, AdapterRegistry

    adapter = get_adapter("claude_desktop")
    adapter.register_server("my-server", {"command": "python", "args": ["server.py"]})
    servers = adapter.discover_servers()
"""
from src.multimcp.adapters.registry import AdapterRegistry, get_adapter, list_adapters
from src.multimcp.adapters.base import MCPConfigAdapter

__all__ = [
    "AdapterRegistry",
    "get_adapter",
    "list_adapters",
    "MCPConfigAdapter",
]
