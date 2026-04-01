"""Antigravity IDE MCP config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class AntigravityAdapter(MCPConfigAdapter):
    """Adapter for the Antigravity IDE.

    Config lives at ``~/.gemini/antigravity/mcp_config.json`` on all platforms.
    On Windows the same path is resolved relative to ``%USERPROFILE%``.
    """

    tool_name = "antigravity"
    display_name = "Antigravity"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to Antigravity's mcp_config.json."""
        return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"

    def read_config(self) -> Dict:
        """Read Antigravity's config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to Antigravity's mcp_config.json with a trailing newline."""
        path = self.config_path()
        assert path is not None
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcpServers`` key."""
        data = self.read_config()
        data.setdefault("mcpServers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from Antigravity's ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
