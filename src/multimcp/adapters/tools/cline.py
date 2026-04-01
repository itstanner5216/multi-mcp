"""Cline VS Code extension MCP config adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter

_EXTENSION_STORAGE = "saoudrizwan.claude-dev"
_SETTINGS_RELATIVE = Path("settings") / "cline_mcp_settings.json"


class ClineAdapter(MCPConfigAdapter):
    """Adapter for the Cline VS Code extension.

    Cline stores its MCP settings in VS Code's extension global-storage
    directory.  Paths by platform:

    * **Linux**: ``~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json``
    * **macOS**: ``~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json``
    * **Windows**: ``%APPDATA%\\Code\\User\\globalStorage\\saoudrizwan.claude-dev\\settings\\cline_mcp_settings.json``

    A CLI-mode fallback path ``~/.cline/data/settings/cline_mcp_settings.json``
    is also checked when the VS Code path does not exist.
    """

    tool_name = "cline"
    display_name = "Cline"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def _vscode_path(self) -> Path:
        """Return the VS Code global-storage path for Cline's settings."""
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        elif sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        else:
            base = Path.home() / ".config"
        return base / "Code" / "User" / "globalStorage" / _EXTENSION_STORAGE / _SETTINGS_RELATIVE

    def _cli_path(self) -> Path:
        """Return the CLI-mode fallback path for Cline's settings."""
        return Path.home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json"

    def config_path(self) -> Optional[Path]:
        """Return the active Cline MCP settings path.

        Prefers the VS Code global-storage location; falls back to the CLI path
        when the VS Code path does not exist.
        """
        vscode = self._vscode_path()
        if vscode.exists():
            return vscode
        return self._cli_path()

    def read_config(self) -> Dict:
        """Read Cline's MCP settings, returning {} if the file is absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to Cline's MCP settings file."""
        path = self.config_path()
        assert path is not None
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcpServers`` key."""
        data = self.read_config()
        data.setdefault("mcpServers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from Cline's ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
