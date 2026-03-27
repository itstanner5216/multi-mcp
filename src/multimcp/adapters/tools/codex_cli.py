"""Codex CLI MCP config adapter (TOML format)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters._toml_helpers import read_toml, write_toml
from src.multimcp.adapters.base import MCPConfigAdapter


class CodexCLIAdapter(MCPConfigAdapter):
    """Adapter for the OpenAI Codex CLI tool."""

    tool_name = "codex_cli"
    display_name = "Codex CLI"
    config_format = "toml"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to Codex CLI's config.toml."""
        return Path.home() / ".codex" / "config.toml"

    def read_config(self) -> Dict:
        """Read Codex CLI's TOML config, returning {} if absent."""
        path = self.config_path()
        if path is None:
            return {}
        return read_toml(path)

    def write_config(self, data: Dict) -> None:
        """Write *data* to Codex CLI's config.toml."""
        path = self.config_path()
        assert path is not None
        write_toml(path, data)

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcp_servers`` key."""
        data = self.read_config()
        data.setdefault("mcp_servers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from Codex CLI's ``mcp_servers`` key."""
        return self.read_config().get("mcp_servers", {})
