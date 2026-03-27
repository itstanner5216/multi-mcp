"""Zed editor MCP config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class ZedAdapter(MCPConfigAdapter):
    """Adapter for the Zed code editor."""

    tool_name = "zed"
    display_name = "Zed"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to Zed's settings.json."""
        return Path.home() / ".config" / "zed" / "settings.json"

    def read_config(self) -> Dict:
        """Read Zed's settings.json, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to Zed's settings.json."""
        path = self.config_path()
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``context_servers`` key."""
        data = self.read_config()
        data.setdefault("context_servers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from Zed's ``context_servers`` key."""
        return self.read_config().get("context_servers", {})
