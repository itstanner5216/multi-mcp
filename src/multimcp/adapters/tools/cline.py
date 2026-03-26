"""Cline MCP config adapter.

Config files: JSON
  VS Code extension: <vscode-globalStorage>/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
  CLI:               ~/.cline/data/settings/cline_mcp_settings.json

This adapter targets the CLI path; the VS Code path varies per OS / VS Code
installation and cannot be resolved portably without querying VS Code.

Schema (researched from https://docs.cline.bot/mcp/adding-and-configuring-servers):
  {
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" },
        "disabled": false,
        "autoApprove": []
      }
    }
  }

NOTE: https://docs.cline.bot was inaccessible at build time; schema based on
known community patterns and Cline's public documentation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class ClineAdapter(MCPConfigAdapter):
    """Adapter for Cline (CLI path at ~/.cline/data/settings/cline_mcp_settings.json)."""

    tool_name = "cline"
    display_name = "Cline"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the Cline CLI config file path."""
        return Path.home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json"

    def read_config(self) -> dict:
        """Read and parse the Cline MCP settings JSON file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Cline MCP settings JSON file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Cline config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Cline MCP config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
