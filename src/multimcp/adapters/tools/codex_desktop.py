"""Codex Desktop App MCP config adapter.

Config file: TOML — shared with Codex CLI at ~/.codex/config.toml

Schema (same as Codex CLI):
  [mcp_servers.<name>]
  command = "<executable>"
  args = ["<arg1>", ...]

  [mcp_servers.<name>.env]
  KEY = "value"

NOTE: https://developers.openai.com/codex/app/features/ was inaccessible at
build time; schema based on known community patterns and OpenAI Codex
public documentation showing the Desktop app shares the CLI config file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter
from src.multimcp.adapters._toml_helpers import read_toml, write_toml


class CodexDesktopAdapter(MCPConfigAdapter):
    """Adapter for the Codex Desktop App (shares ~/.codex/config.toml with Codex CLI)."""

    tool_name = "codex_desktop"
    display_name = "Codex Desktop"
    config_format = "toml"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the shared Codex config file path."""
        return Path.home() / ".codex" / "config.toml"

    def read_config(self) -> dict:
        """Read and parse the Codex TOML config file."""
        path = self.config_path()
        if path is None:
            return {}
        return read_toml(path)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the Codex TOML config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        write_toml(path, config)

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the Codex Desktop config."""
        config = self.read_config()
        return dict(config.get("mcp_servers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Codex Desktop TOML config."""
        config = self.read_config()
        config.setdefault("mcp_servers", {})[server_name] = server_config
        self.write_config(config)
