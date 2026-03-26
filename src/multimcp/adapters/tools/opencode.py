"""OpenCode MCP config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class OpenCodeAdapter(MCPConfigAdapter):
    """Adapter for the OpenCode AI assistant.

    OpenCode stores MCP servers under the ``mcp`` key in its config.json.
    """

    tool_name = "opencode"
    display_name = "OpenCode"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to OpenCode's config.json."""
        return Path.home() / ".config" / "opencode" / "config.json"

    def read_config(self) -> Dict:
        """Read OpenCode's config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to OpenCode's config.json."""
        path = self.config_path()
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcp`` key."""
        data = self.read_config()
        data.setdefault("mcp", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from OpenCode's ``mcp`` key."""
        return self.read_config().get("mcp", {})
