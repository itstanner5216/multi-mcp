"""Antigravity IDE MCP config adapter.

Config file: JSON
  Path: mcp_config.json  (managed via the MCP Store UI within Antigravity IDE)
  The file is typically located in the project root or the Antigravity IDE
  user config directory.  Because Antigravity manages this file through its
  UI, the exact path may vary; this adapter targets the project-root location.

Schema (researched from https://antigravity.google/docs/mcp):
  {
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    }
  }

NOTE: https://antigravity.google/docs/mcp was inaccessible at build time;
schema based on known community patterns for Google-ecosystem MCP tooling.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class AntigravityAdapter(MCPConfigAdapter):
    """Adapter for Antigravity IDE (project-root mcp_config.json)."""

    tool_name = "antigravity"
    display_name = "Antigravity IDE"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the project-root Antigravity MCP config file path."""
        return Path.cwd() / "mcp_config.json"

    def read_config(self) -> dict:
        """Read and parse the Antigravity MCP JSON config file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Antigravity MCP JSON config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Antigravity config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Antigravity MCP config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
