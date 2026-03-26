"""Roo Code MCP config adapter.

Config files: JSON
  Project: .roo/mcp.json
  Global (VS Code globalStorage): varies per OS — adapter targets project file.

Schema (researched from https://docs.roocode.com/features/mcp/using-mcp-in-roo):
  {
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" },
        "disabled": false,
        "alwaysAllow": []
      }
    }
  }

NOTE: https://docs.roocode.com was inaccessible at build time; schema based on
known community patterns and Roo Code public documentation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class RooCodeAdapter(MCPConfigAdapter):
    """Adapter for Roo Code (VS Code extension) project-level MCP config."""

    tool_name = "roo_code"
    display_name = "Roo Code"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the project-level Roo Code MCP config path."""
        return Path.cwd() / ".roo" / "mcp.json"

    def read_config(self) -> dict:
        """Read and parse the Roo Code MCP JSON config file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Roo Code MCP JSON config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Roo Code config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Roo Code MCP config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
