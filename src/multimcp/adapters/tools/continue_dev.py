"""Continue.dev MCP config adapter.

Config files: YAML — one file per MCP server under .continue/mcpServers/
  Path pattern: <project>/.continue/mcpServers/<name>.yaml
  Global (home):  ~/.continue/mcpServers/<name>.yaml

Schema (researched from https://docs.continue.dev/customize/deep-dives/mcp):
  # stdio server
  name: <server_name>
  command: <executable>
  args:
    - <arg1>
  env:
    KEY: value

  # SSE / HTTP server
  name: <server_name>
  url: http://localhost:8080/sse

NOTE: https://docs.continue.dev/customize/deep-dives/mcp was inaccessible at
build time; schema based on known community patterns and Continue.dev public docs.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter
from src.utils.logger import get_logger

_logger = get_logger("multi_mcp.adapters.continue_dev")


class ContinueDevAdapter(MCPConfigAdapter):
    """Adapter for Continue.dev (global ~/.continue/mcpServers/ directory)."""

    tool_name = "continue_dev"
    display_name = "Continue.dev"
    config_format = "yaml"
    supported_platforms = ["macos", "linux", "windows"]

    def _servers_dir(self) -> Path:
        """Return the path to the global mcpServers directory."""
        return Path.home() / ".continue" / "mcpServers"

    def config_path(self) -> Optional[Path]:
        """Return the mcpServers directory (not a single file).

        For compatibility with the base interface this returns the directory
        path.  Individual server files are managed by :meth:`register_server`.
        """
        return self._servers_dir()

    def read_config(self) -> dict:
        """Read all per-server YAML files and return them as a combined dict.

        Returns ``{"<name>": <server_config_dict>, ...}``.
        """
        servers_dir = self._servers_dir()
        if not servers_dir.exists():
            return {}
        result: dict = {}
        for yaml_file in sorted(servers_dir.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                name = data.get("name") or yaml_file.stem
                result[name] = data
            except (OSError, yaml.YAMLError) as exc:
                _logger.warning(f"⚠️ Skipping malformed Continue.dev config file {yaml_file}: {exc}")
        return result

    def write_config(self, config: dict) -> None:
        """Write the combined *config* dict back as individual YAML files.

        Each key in *config* becomes ``<key>.yaml`` inside the servers directory.
        The value dict is expected to already contain a ``name`` field.
        """
        servers_dir = self._servers_dir()
        servers_dir.mkdir(parents=True, exist_ok=True)
        for name, server_data in config.items():
            file_path = servers_dir / f"{name}.yaml"
            with open(file_path, "w", encoding="utf-8") as fh:
                yaml.dump(server_data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers found in ~/.continue/mcpServers/."""
        return self.read_config()

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Write or overwrite the YAML file for *server_name*.

        *server_config* may contain ``command``/``args``/``env`` (stdio) or
        ``url`` (SSE).  A ``name`` field is automatically added.
        """
        servers_dir = self._servers_dir()
        servers_dir.mkdir(parents=True, exist_ok=True)
        data = {"name": server_name, **server_config}
        file_path = servers_dir / f"{server_name}.yaml"
        with open(file_path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
