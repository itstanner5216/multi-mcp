"""Gemini CLI MCP config adapter.

Config files: JSON
  Global:  ~/.gemini/settings.json
  Project: .gemini/settings.json

Schema (researched from https://github.com/google-gemini/gemini-cli):
  {
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" },
        "timeout": 30000,
        "trust": false
      }
    }
  }

NOTE: https://geminicli.com/docs/cli/tutorials/mcp-setup/ was inaccessible at
build time; schema based on the gemini-cli GitHub repository and known
community patterns.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class GeminiCLIAdapter(MCPConfigAdapter):
    """Adapter for the Gemini CLI (global ~/.gemini/settings.json)."""

    tool_name = "gemini_cli"
    display_name = "Gemini CLI"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the global Gemini CLI settings file path."""
        return Path.home() / ".gemini" / "settings.json"

    def read_config(self) -> dict:
        """Read and parse the Gemini CLI settings JSON file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Gemini CLI settings JSON file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Gemini CLI config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Gemini CLI config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
