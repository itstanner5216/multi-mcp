"""Raycast MCP config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class RaycastAdapter(MCPConfigAdapter):
    """Adapter for the Raycast launcher.

    Config location:

    * **macOS / Linux**: ``~/.config/raycast/mcp.json``

    Raycast is a macOS-first application but the config path follows the
    XDG-style convention used across platforms.
    """

    tool_name = "raycast"
    display_name = "Raycast"
    config_format = "json"
    supported_platforms = ["macos", "linux"]

    def config_path(self) -> Optional[Path]:
        """Return the Raycast MCP config path."""
        return Path.home() / ".config" / "raycast" / "mcp.json"

    def read_config(self) -> Dict:
        """Read the Raycast MCP config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to the Raycast MCP config."""
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
        """Return all servers from Raycast's ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
