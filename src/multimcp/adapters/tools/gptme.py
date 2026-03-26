"""gptme MCP config adapter.

Config files: TOML
  Global:  ~/.config/gptme/config.toml
  Project: gptme.toml
  Secrets: ~/.config/gptme/config.local.toml  (not modified by this adapter)

Schema (researched from https://gptme.org/docs/config.html):
  [[mcp.servers]]
  name = "<server_name>"
  url = "http://localhost:8080/sse"   # SSE server

  # or for stdio:
  [[mcp.servers]]
  name = "<server_name>"
  command = "<executable> <args>"     # space-separated command string

NOTE: https://gptme.org/docs/config.html was inaccessible at build time;
schema based on known community patterns and gptme public documentation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter
from src.multimcp.adapters._toml_helpers import read_toml, write_toml


class GptmeAdapter(MCPConfigAdapter):
    """Adapter for gptme (global ~/.config/gptme/config.toml)."""

    tool_name = "gptme"
    display_name = "gptme"
    config_format = "toml"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the global gptme config file path."""
        return Path.home() / ".config" / "gptme" / "config.toml"

    def read_config(self) -> dict:
        """Read and parse the gptme TOML config file."""
        path = self.config_path()
        if path is None:
            return {}
        return read_toml(path)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the gptme TOML config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        write_toml(path, config)

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the gptme config.

        The gptme TOML schema uses an array of tables under ``mcp.servers``;
        this method returns them as a ``{name: config}`` dict for consistency.
        """
        config = self.read_config()
        servers = config.get("mcp", {}).get("servers", [])
        result: dict = {}
        for entry in servers:
            name = entry.get("name", "")
            if name:
                result[name] = entry
        return result

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the gptme MCP config.

        If an entry with the same name already exists it is replaced; otherwise
        a new entry is appended to ``[[mcp.servers]]``.
        """
        config = self.read_config()
        mcp_section = config.setdefault("mcp", {})
        servers: list = mcp_section.setdefault("servers", [])

        entry = {"name": server_name, **server_config}

        # Replace existing entry or append
        for i, existing in enumerate(servers):
            if existing.get("name") == server_name:
                servers[i] = entry
                break
        else:
            servers.append(entry)

        self.write_config(config)
