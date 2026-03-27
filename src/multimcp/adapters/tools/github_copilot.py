"""GitHub Copilot (VS Code) MCP config adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class GitHubCopilotAdapter(MCPConfigAdapter):
    """Adapter for GitHub Copilot in VS Code.

    GitHub Copilot reads MCP servers from ``~/.vscode/mcp.json`` using a
    ``servers`` key (not ``mcpServers``).
    """

    tool_name = "github_copilot"
    display_name = "GitHub Copilot"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to VS Code's MCP config file."""
        return Path.home() / ".vscode" / "mcp.json"

    def read_config(self) -> Dict:
        """Read the VS Code MCP config, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to the VS Code MCP config file."""
        path = self.config_path()
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``servers`` key."""
        data = self.read_config()
        data.setdefault("servers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from the VS Code MCP ``servers`` key."""
        return self.read_config().get("servers", {})
