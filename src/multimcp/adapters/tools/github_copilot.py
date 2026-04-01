"""GitHub Copilot CLI MCP config adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class GitHubCopilotAdapter(MCPConfigAdapter):
    """Adapter for the GitHub Copilot CLI.

    GitHub Copilot CLI reads MCP servers from ``~/.copilot/mcp-config.json``.
    On Windows the path resolves to ``%USERPROFILE%\\.copilot\\mcp-config.json``.
    """

    tool_name = "github_copilot"
    display_name = "GitHub Copilot CLI"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to GitHub Copilot CLI's MCP config file."""
        if sys.platform == "win32":
            base = Path(os.environ.get("USERPROFILE", Path.home()))
        else:
            base = Path.home()
        return base / ".copilot" / "mcp-config.json"

    def read_config(self) -> Dict:
        """Read the GitHub Copilot CLI MCP config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to the GitHub Copilot CLI MCP config file."""
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
        """Return all servers from the GitHub Copilot CLI ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
