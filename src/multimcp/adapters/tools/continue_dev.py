"""Continue.dev MCP config adapter."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.multimcp.adapters.base import MCPConfigAdapter


class ContinueDevAdapter(MCPConfigAdapter):
    """Adapter for the Continue.dev VS Code / JetBrains extension.

    Continue stores its full configuration in a single ``config.yaml`` file:

    * **Linux / macOS**: ``~/.continue/config.yaml``
    * **Windows**: ``%USERPROFILE%\\.continue\\config.yaml``

    MCP servers live under the top-level ``mcpServers`` list in that file, each
    item being a dict with at least a ``name`` key.
    """

    tool_name = "continue_dev"
    display_name = "Continue.dev"
    config_format = "yaml"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the path to Continue's config.yaml."""
        if sys.platform == "win32":
            base = Path(os.environ.get("USERPROFILE", Path.home()))
        else:
            base = Path.home()
        return base / ".continue" / "config.yaml"

    def read_config(self) -> Dict:
        """Read Continue's config.yaml, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def write_config(self, data: Dict) -> None:
        """Write *data* to Continue's config.yaml."""
        path = self.config_path()
        assert path is not None
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def register_server(self, name: str, config: Dict) -> None:
        """Add or replace an entry in the ``mcpServers`` list."""
        data = self.read_config()
        servers: List[Any] = data.setdefault("mcpServers", [])
        # Remove any existing entry with the same name
        servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == name)]
        servers.append({"name": name, **config})
        data["mcpServers"] = servers
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return a name→config mapping from the ``mcpServers`` list."""
        servers_list = self.read_config().get("mcpServers", [])
        return {
            s["name"]: {k: v for k, v in s.items() if k != "name"}
            for s in servers_list
            if isinstance(s, dict) and "name" in s
        }
