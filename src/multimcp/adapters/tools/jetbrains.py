"""JetBrains IDE MCP config adapter (read-only discovery)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class JetBrainsAdapter(MCPConfigAdapter):
    """Read-only adapter for JetBrains IDEs.

    JetBrains manages MCP servers through its own UI; programmatic writes are
    not supported.  ``register_server`` and ``write_config`` raise
    ``NotImplementedError`` to make that explicit.
    """

    tool_name = "jetbrains"
    display_name = "JetBrains IDEs"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def _jetbrains_root(self) -> Path:
        """Return the root JetBrains config directory."""
        return Path.home() / ".config" / "JetBrains"

    def config_path(self) -> Optional[Path]:
        """Return the JetBrains config root directory."""
        return self._jetbrains_root()

    def read_config(self) -> Dict:
        """Return a best-effort view of registered MCP servers.

        Scans known config locations; returns {} when none are found.
        """
        root = self._jetbrains_root()
        if not root.exists():
            return {}
        result: Dict = {}
        for mcp_file in root.rglob("mcp.json"):
            try:
                data = json.loads(mcp_file.read_text(encoding="utf-8"))
                result.update(data)
            except (json.JSONDecodeError, OSError):
                pass
        return result

    def write_config(self, data: Dict) -> None:
        """Not supported – JetBrains config must be managed through the IDE UI."""
        raise NotImplementedError(
            "JetBrains MCP config must be managed through the IDE UI."
        )

    def register_server(self, name: str, config: Dict) -> None:
        """Not supported – JetBrains config must be managed through the IDE UI."""
        raise NotImplementedError(
            "JetBrains MCP server registration must be done through the IDE UI."
        )

    def discover_servers(self) -> Dict[str, Dict]:
        """Return discovered MCP servers from JetBrains config files."""
        root = self._jetbrains_root()
        if not root.exists():
            return {}
        result: Dict = {}
        for mcp_file in root.rglob("mcp.json"):
            try:
                data = json.loads(mcp_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    result.update(data)
            except (json.JSONDecodeError, OSError):
                pass
        return result
