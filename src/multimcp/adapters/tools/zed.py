"""Zed editor MCP config adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class ZedAdapter(MCPConfigAdapter):
    """Adapter for the Zed code editor.

    Config file locations:

    * **Linux**: ``~/.config/zed/settings.json``
    * **macOS**: ``~/.zed/settings.json``
    * **Windows**: ``%APPDATA%\\Zed\\settings.json``

    Zed uses the ``context_servers`` key for MCP server entries.
    """

    tool_name = "zed"
    display_name = "Zed"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the platform-specific path to Zed's settings.json."""
        if sys.platform == "darwin":
            base = Path.home() / ".zed"
        elif sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
            return base / "Zed" / "settings.json"
        else:
            base = Path.home() / ".config" / "zed"
        return base / "settings.json"

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
        self._backup(path)
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
