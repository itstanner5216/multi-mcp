"""OpenCode MCP config adapter.

Config files: JSON
  Project: opencode.json
  Global:  ~/.config/opencode/config.json

Schema (researched from https://opencode.ai/docs/mcp-servers/):
  {
    "mcp": {
      "<name>": {
        "type": "local",
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    }
  }
  Remote SSE variant uses "type": "remote" and "url": "...".

NOTE: https://opencode.ai/docs/mcp-servers/ was inaccessible at build time;
schema based on known community patterns and OpenCode's public documentation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class OpenCodeAdapter(MCPConfigAdapter):
    """Adapter for OpenCode (global ~/.config/opencode/config.json)."""

    tool_name = "opencode"
    display_name = "OpenCode"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the global OpenCode config file path."""
        return Path.home() / ".config" / "opencode" / "config.json"

    def read_config(self) -> dict:
        """Read and parse the OpenCode JSON config file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the OpenCode JSON config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the OpenCode config."""
        config = self.read_config()
        return dict(config.get("mcp", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the OpenCode MCP config."""
        config = self.read_config()
        config.setdefault("mcp", {})[server_name] = server_config
        self.write_config(config)
