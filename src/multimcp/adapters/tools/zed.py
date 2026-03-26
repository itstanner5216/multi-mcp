"""Zed IDE MCP config adapter.

Config file: JSON
  Global:  ~/.config/zed/settings.json
  Project: .zed/settings.json

Schema (researched from https://zed.dev/docs/assistant/model-context-protocol):
  {
    "context_servers": {
      "<name>": {
        "command": {
          "path": "<executable>",
          "args": ["<arg1>", ...],
          "env": { "KEY": "value" }
        }
      }
    }
  }
  SSE variant uses "settings": { "port": <port> } under the server entry.

NOTE: https://zed.dev/docs/assistant/model-context-protocol was inaccessible at
build time; schema based on known community patterns and Zed's public docs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class ZedAdapter(MCPConfigAdapter):
    """Adapter for the Zed IDE (global settings)."""

    tool_name = "zed"
    display_name = "Zed IDE"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the global Zed settings file path."""
        return Path.home() / ".config" / "zed" / "settings.json"

    def read_config(self) -> dict:
        """Read and parse the Zed settings JSON file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Zed settings JSON file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP context servers registered in the Zed settings."""
        config = self.read_config()
        return dict(config.get("context_servers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Zed context_servers config.

        *server_config* should contain a ``"command"`` dict with ``"path"``,
        optional ``"args"`` and ``"env"`` keys, which is Zed's expected schema.
        """
        config = self.read_config()
        config.setdefault("context_servers", {})[server_name] = server_config
        self.write_config(config)
