"""Public API for MCP config adapters.

Usage::

    from src.multimcp.adapters import AdapterRegistry, get_adapter, list_adapters

    adapter = get_adapter("claude_desktop")
    adapter.register_server("my-mcp", {"command": "uvx", "args": ["mcp-server"]})
"""
from __future__ import annotations

from typing import List, Optional

from src.multimcp.adapters.base import MCPConfigAdapter
from src.multimcp.adapters.registry import AdapterRegistry

_registry: Optional[AdapterRegistry] = None


def _get_registry() -> AdapterRegistry:
    """Return the singleton adapter registry, creating it on first call."""
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


def get_adapter(tool_name: str) -> Optional[MCPConfigAdapter]:
    """Return the adapter for *tool_name*, or None if not found."""
    return _get_registry().get(tool_name)


def list_adapters() -> List[MCPConfigAdapter]:
    """Return all registered adapters sorted by tool name."""
    return _get_registry().all()


__all__ = [
    "AdapterRegistry",
    "MCPConfigAdapter",
    "get_adapter",
    "list_adapters",
]
