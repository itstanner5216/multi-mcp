"""Raycast MCP config adapter (macOS-only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class RaycastAdapter(MCPConfigAdapter):
    """Adapter for the Raycast launcher (macOS only)."""

    tool_name = "raycast"
    display_name = "Raycast"
    config_format = "json"
    supported_platforms = ["macos"]

    def config_path(self) -> Optional[Path]:
        """Return the Raycast MCP config path, or None on non-macOS platforms."""
        if sys.platform != "darwin":
            return None
        return (
            Path.home()
            / "Library"
            / "Preferences"
            / "com.raycast.macos"
            / "mcp-config.json"
        )

    def read_config(self) -> Dict:
        """Read the Raycast MCP config, returning {} if absent or on non-macOS."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to the Raycast MCP config.

        Raises ``RuntimeError`` on non-macOS platforms.
        """
        path = self.config_path()
        if path is None:
            raise RuntimeError("Raycast is only supported on macOS.")
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
