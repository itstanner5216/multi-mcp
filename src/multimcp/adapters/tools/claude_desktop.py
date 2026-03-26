"""Claude Desktop MCP config adapter.

Config file: JSON
  macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
  Windows: %APPDATA%\\Claude\\claude_desktop_config.json
  Linux:   ~/.config/Claude/claude_desktop_config.json

Schema (researched from https://modelcontextprotocol.io/docs/develop/connect-local-servers):
  {
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    }
  }
  SSE variant uses "url" instead of "command"/"args".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter, _current_platform


class ClaudeDesktopAdapter(MCPConfigAdapter):
    """Adapter for the Claude Desktop application."""

    tool_name = "claude_desktop"
    display_name = "Claude Desktop"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the platform-specific config file path."""
        platform = _current_platform()
        if platform == "macos":
            return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        elif platform == "windows":
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                return None
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        elif platform == "linux":
            return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
        return None

    def read_config(self) -> dict:
        """Read and parse the JSON config file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the JSON config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Claude Desktop config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Claude Desktop config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
