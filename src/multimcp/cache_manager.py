from __future__ import annotations
from typing import List, Set
from mcp import types
from src.multimcp.yaml_config import MultiMCPConfig, ToolEntry


def merge_discovered_tools(
    config: MultiMCPConfig,
    server_name: str,
    discovered: List[types.Tool],
) -> MultiMCPConfig:
    """Merge newly discovered tools into existing config.

    Rules:
    - New tool: add with enabled=True
    - Existing tool: preserve enabled, update description, clear stale
    - Tool gone from server: mark stale=True, preserve enabled
    """
    server = config.servers.get(server_name)
    if server is None:
        return config
    discovered_names = {t.name for t in discovered}

    # Mark gone tools as stale
    for tool_name, entry in server.tools.items():
        if tool_name not in discovered_names:
            entry.stale = True

    # Add or update discovered tools
    for tool in discovered:
        if tool.name in server.tools:
            entry = server.tools[tool.name]
            entry.description = tool.description or ""
            entry.stale = False
        else:
            server.tools[tool.name] = ToolEntry(
                enabled=True,
                stale=False,
                description=tool.description or "",
            )

    return config


def cleanup_stale_tools(config: MultiMCPConfig, server_name: str) -> int:
    """Remove tools that are both stale and disabled. Returns count removed."""
    server = config.servers.get(server_name)
    if not server:
        return 0
    to_remove = [
        name for name, entry in server.tools.items()
        if entry.stale and not entry.enabled
    ]
    for name in to_remove:
        del server.tools[name]
    return len(to_remove)


def get_enabled_tools(config: MultiMCPConfig, server_name: str) -> Set[str]:
    """Return set of tool names that should be exposed for a server."""
    server = config.servers.get(server_name)
    if not server:
        return set()
    return {
        name for name, entry in server.tools.items()
        if entry.enabled and not entry.stale
    }
