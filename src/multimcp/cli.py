from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional
from src.multimcp.yaml_config import load_config, MultiMCPConfig
from src.multimcp.cache_manager import merge_discovered_tools, cleanup_stale_tools
from src.utils.logger import get_logger

logger = get_logger("multi_mcp.cli")
DEFAULT_YAML = Path.home() / ".config" / "multi-mcp" / "servers.yaml"


def cmd_list(
    yaml_path: Path = DEFAULT_YAML,
    server_filter: Optional[str] = None,
    disabled_only: bool = False,
) -> str:
    config = load_config(yaml_path)
    if not config.servers:
        return "No servers configured. Run: multi-mcp start (first run will discover servers)"

    lines = []
    for server_name, server_config in config.servers.items():
        if server_filter and server_name != server_filter:
            continue
        enabled_count = sum(1 for t in server_config.tools.values() if t.enabled and not t.stale)
        total = len(server_config.tools)
        if lines:
            lines.append("")
        lines.append(f"[{server_name}] ({enabled_count}/{total} tools enabled)")
        for tool_name, entry in sorted(server_config.tools.items()):
            if disabled_only and entry.enabled and not entry.stale:
                continue
            if entry.stale:
                status = "⚠"
                label = f" [stale]"
            elif entry.enabled:
                status = "✓"
                label = ""
            else:
                status = "✗"
                label = ""
            lines.append(f"  {status} {tool_name}{label}")

    return "\n".join(lines)


def cmd_status(yaml_path: Path = DEFAULT_YAML) -> str:
    config = load_config(yaml_path)
    if not config.servers:
        return "No servers configured."

    lines = ["Multi-MCP Status", "=" * 40]
    for server_name, server_config in config.servers.items():
        stale = sum(1 for t in server_config.tools.values() if t.stale)
        enabled = sum(1 for t in server_config.tools.values() if t.enabled and not t.stale)
        disabled = sum(1 for t in server_config.tools.values() if not t.enabled and not t.stale)
        mode = "always_on" if server_config.always_on else f"lazy ({server_config.idle_timeout_minutes}m timeout)"
        lines.append(f"\n{server_name}")
        lines.append(f"  Mode:     {mode}")
        lines.append(f"  Tools:    {enabled} enabled, {disabled} disabled, {stale} stale")
        if server_config.command:
            lines.append(f"  Command:  {server_config.command}")
        elif server_config.url:
            lines.append(f"  URL:      {server_config.url}")

    return "\n".join(lines)


async def cmd_refresh(
    server_filter: Optional[str] = None,
    yaml_path: Path = DEFAULT_YAML,
) -> str:
    from src.multimcp.mcp_client import MCPClientManager
    from src.multimcp.yaml_config import save_config

    config = load_config(yaml_path)
    if not config.servers:
        return "No servers configured."

    manager = MCPClientManager()
    if server_filter:
        if server_filter not in config.servers:
            return f"Unknown server: {server_filter}"
        from src.multimcp.yaml_config import MultiMCPConfig
        partial = MultiMCPConfig(servers={server_filter: config.servers[server_filter]})
    else:
        partial = config

    discovered = await manager.discover_all(partial)

    for name, tools in discovered.items():
        merge_discovered_tools(config, name, tools)
        cleaned = cleanup_stale_tools(config, name)
        if cleaned:
            logger.info(f"🧹 Cleaned up {cleaned} stale+disabled tools from '{name}'")

    zero_tool_servers = [name for name, tools in discovered.items() if not tools]

    save_config(config, yaml_path)
    total_tools = sum(len(t) for t in discovered.values())
    warning = ""
    if zero_tool_servers:
        warning = f"\n⚠️  0 tools discovered for: {', '.join(zero_tool_servers)} — check server config"
    return f"✅ Refreshed {len(discovered)} server(s), {total_tools} tools discovered. Saved to {yaml_path}{warning}"
