"""Warp Terminal MCP config adapter.

Config files: JSON (per OS)
  macOS:   ~/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/mcp/
           (directory — one JSON file per server: <name>.json)
  Linux:   ~/.config/warp-terminal/mcp_servers.json
  Windows: %LOCALAPPDATA%\\warp\\Warp\\data\\mcp\\
           (directory — one JSON file per server: <name>.json)

Schema for per-server JSON file (macOS/Windows directory mode):
  {
    "name": "<server_name>",
    "command": "<executable>",
    "args": ["<arg1>", ...],
    "env": { "KEY": "value" }
  }

Schema for Linux single-file mode:
  {
    "data": [
      {
        "name": "<server_name>",
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    ]
  }

NOTE: https://docs.warp.dev was inaccessible at build time; schema based on
known community patterns and Warp Terminal's public documentation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter
from src.utils.logger import get_logger

_logger = get_logger("multi_mcp.adapters.warp")


class WarpAdapter(MCPConfigAdapter):
    """Adapter for Warp Terminal MCP configuration."""

    tool_name = "warp"
    display_name = "Warp Terminal"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def _is_dir_mode(self) -> bool:
        """Return True on macOS/Windows where each server has its own JSON file."""
        return sys.platform in ("darwin", "win32")

    def config_path(self) -> Optional[Path]:
        """Return the config path (directory on macOS/Windows, file on Linux)."""
        if sys.platform == "darwin":
            return (
                Path.home()
                / "Library"
                / "Group Containers"
                / "2BBY89MBSN.dev.warp"
                / "Library"
                / "Application Support"
                / "dev.warp.Warp-Stable"
                / "mcp"
            )
        if sys.platform == "win32":
            localappdata = os.environ.get("LOCALAPPDATA", "")
            if not localappdata:
                return None
            return Path(localappdata) / "warp" / "Warp" / "data" / "mcp"
        # Linux
        return Path.home() / ".config" / "warp-terminal" / "mcp_servers.json"

    def read_config(self) -> dict:
        """Read Warp MCP config.

        On macOS/Windows returns ``{"<name>": <server_dict>, ...}`` by
        scanning the directory.  On Linux parses the single JSON file.
        """
        path = self.config_path()
        if path is None:
            return {}
        if self._is_dir_mode():
            if not path.exists():
                return {}
            result: dict = {}
            for json_file in sorted(path.glob("*.json")):
                try:
                    with open(json_file, encoding="utf-8") as fh:
                        data = json.load(fh)
                    name = data.get("name") or json_file.stem
                    result[name] = data
                except (OSError, json.JSONDecodeError) as exc:
                    _logger.warning(f"⚠️ Skipping malformed Warp config file {json_file}: {exc}")
            return result
        # Linux single-file
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        # Normalise to {name: config} mapping
        result = {}
        for entry in raw.get("data", []):
            name = entry.get("name", "")
            if name:
                result[name] = entry
        return result

    def write_config(self, config: dict) -> None:
        """Write Warp MCP config back to disk.

        On macOS/Windows writes each server as its own ``<name>.json`` file.
        On Linux rewrites the single ``mcp_servers.json`` file.
        """
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        if self._is_dir_mode():
            path.mkdir(parents=True, exist_ok=True)
            for name, server_data in config.items():
                file_path = path / f"{name}.json"
                with open(file_path, "w", encoding="utf-8") as fh:
                    json.dump(server_data, fh, indent=2)
                    fh.write("\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            entries = list(config.values())
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"data": entries}, fh, indent=2)
                fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in Warp Terminal config."""
        return self.read_config()

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the Warp Terminal MCP config."""
        config = self.read_config()
        entry = {"name": server_name, **server_config}
        config[server_name] = entry
        self.write_config(config)
