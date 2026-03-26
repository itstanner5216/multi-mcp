"""Raycast MCP config adapter.

Config file: JSON
  Path: Raycast extension support directory / mcp-config.json
  The path is revealed by "Show Config File in Finder" in the
  Manage MCP Servers extension within Raycast.

  macOS (typical): ~/Library/Application Support/com.raycast.macos/extensions/mcp/mcp-config.json
  Linux / Windows: Not officially supported (Raycast is macOS-only).

Schema (researched from https://github.com/raycast/extensions/tree/main/extensions/mcp):
  {
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    }
  }

NOTE: https://github.com/raycast/extensions/tree/main/extensions/mcp was
inaccessible at build time; schema based on known community patterns and
Raycast MCP extension documentation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter, _current_platform


class RaycastAdapter(MCPConfigAdapter):
    """Adapter for the Raycast MCP extension (macOS only)."""

    tool_name = "raycast"
    display_name = "Raycast"
    config_format = "json"
    supported_platforms = ["macos"]

    def config_path(self) -> Optional[Path]:
        """Return the Raycast MCP config file path."""
        if _current_platform() != "macos":
            return None
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "com.raycast.macos"
            / "extensions"
            / "mcp"
            / "mcp-config.json"
        )

    def read_config(self) -> dict:
        """Read and parse the Raycast MCP JSON config file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Raycast MCP JSON config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: only supported on macOS")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Raycast config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Raycast MCP config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
