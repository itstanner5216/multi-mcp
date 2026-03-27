"""Warp Terminal MCP config adapter.

Warp uses a single JSON file on Linux and a directory of per-server JSON files
on macOS (inside the group-container sandbox).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class WarpAdapter(MCPConfigAdapter):
    """Adapter for the Warp terminal application."""

    tool_name = "warp"
    display_name = "Warp Terminal"
    config_format = "json"
    supported_platforms = ["macos", "linux"]

    def config_path(self) -> Optional[Path]:
        """Return the platform-specific Warp MCP config path."""
        if sys.platform == "darwin":
            return (
                Path.home()
                / "Library"
                / "Group Containers"
                / "2BBY89MBSN.dev.warp"
                / "MCP Servers"
            )
        return Path.home() / ".config" / "warp-terminal" / "mcp_servers.json"

    def _is_dir_mode(self) -> bool:
        """Return True when Warp uses a directory of per-server JSON files."""
        return sys.platform == "darwin"

    def read_config(self) -> Dict:
        """Read the Warp MCP config, returning {} if absent."""
        path = self.config_path()
        if path is None:
            return {}
        if self._is_dir_mode():
            if not path.exists():
                return {}
            result: Dict = {}
            for json_file in sorted(path.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    result[json_file.stem] = data
                except (json.JSONDecodeError, OSError):
                    pass
            return result
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to the Warp MCP config location."""
        path = self.config_path()
        assert path is not None
        if self._is_dir_mode():
            path.mkdir(parents=True, exist_ok=True)
            for name, cfg in data.items():
                (path / f"{name}.json").write_text(
                    json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry in the Warp config."""
        if self._is_dir_mode():
            path = self.config_path()
            assert path is not None
            path.mkdir(parents=True, exist_ok=True)
            (path / f"{name}.json").write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )
        else:
            data = self.read_config()
            data.setdefault("mcpServers", {})[name] = config
            self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all MCP servers from the Warp config."""
        if self._is_dir_mode():
            return self.read_config()
        return self.read_config().get("mcpServers", {})
