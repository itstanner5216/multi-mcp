"""Roo Code VS Code extension MCP config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class RooCodeAdapter(MCPConfigAdapter):
    """Adapter for the Roo Code VS Code extension."""

    tool_name = "roo_code"
    display_name = "Roo Code"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to Roo Code's mcp.json."""
        return Path.home() / ".roo" / "mcp.json"

    def read_config(self) -> Dict:
        """Read Roo Code's MCP config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to Roo Code's mcp.json."""
        path = self.config_path()
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcpServers`` key."""
        data = self.read_config()
        data.setdefault("mcpServers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from Roo Code's ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
