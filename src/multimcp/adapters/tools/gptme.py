"""gptme MCP config adapter (TOML format with array of tables)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from src.multimcp.adapters._toml_helpers import read_toml, write_toml
from src.multimcp.adapters.base import MCPConfigAdapter


class GptmeAdapter(MCPConfigAdapter):
    """Adapter for the gptme command-line AI assistant.

    gptme stores MCP servers as a TOML array of tables under ``[mcp.servers]``,
    each entry having a ``name`` field alongside the server configuration.
    """

    tool_name = "gptme"
    display_name = "gptme"
    config_format = "toml"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to gptme's config.toml."""
        return Path.home() / ".config" / "gptme" / "config.toml"

    def read_config(self) -> Dict:
        """Read gptme's TOML config, returning {} if absent."""
        path = self.config_path()
        if path is None:
            return {}
        return read_toml(path)

    def write_config(self, data: Dict) -> None:
        """Write *data* to gptme's config.toml."""
        path = self.config_path()
        assert path is not None
        self._backup(path)
        write_toml(path, data)

    def register_server(self, name: str, config: Dict) -> None:
        """Add or replace an entry in the ``mcp.servers`` array."""
        data = self.read_config()
        servers: List[Dict] = data.setdefault("mcp", {}).setdefault("servers", [])
        # Remove any existing entry with the same name
        servers = [s for s in servers if s.get("name") != name]
        servers.append({"name": name, **config})
        data["mcp"]["servers"] = servers
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return a name→config mapping from the ``mcp.servers`` array."""
        servers_list = self.read_config().get("mcp", {}).get("servers", [])
        return {
            s["name"]: {k: v for k, v in s.items() if k != "name"}
            for s in servers_list
            if "name" in s
        }
