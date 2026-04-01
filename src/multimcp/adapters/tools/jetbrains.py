"""JetBrains IDEs MCP config adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class JetBrainsAdapter(MCPConfigAdapter):
    """Adapter for JetBrains IDEs (IntelliJ, PyCharm, WebStorm, etc.).

    JetBrains stores MCP configuration in a shared ``mcp.json`` file under
    the Junie plugin directory:

    * **Linux / macOS**: ``~/.junie/mcp/mcp.json``
    * **Windows**: ``%USERPROFILE%\\.junie\\mcp\\mcp.json``
    """

    tool_name = "jetbrains"
    display_name = "JetBrains IDEs"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to the JetBrains Junie MCP config file."""
        if sys.platform == "win32":
            userprofile = os.environ.get("USERPROFILE")
            base = Path(userprofile) if userprofile else Path.home()
        else:
            base = Path.home()
        return base / ".junie" / "mcp" / "mcp.json"

    def read_config(self) -> Dict:
        """Read the JetBrains MCP config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def write_config(self, data: Dict) -> None:
        """Write *data* to the JetBrains Junie MCP config file."""
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
        """Return all servers from the JetBrains Junie ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
