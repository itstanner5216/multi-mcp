"""Claude Desktop MCP config adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class ClaudeDesktopAdapter(MCPConfigAdapter):
    """Adapter for Anthropic's Claude Desktop application.

    Supports both the Desktop App and the Claude Code CLI config files.
    The Desktop App config locations are:

    * **macOS**: ``~/Library/Application Support/Claude/claude_desktop_config.json``
    * **Windows**: ``%APPDATA%\\Claude\\claude_desktop_config.json``
    * **Linux**: ``~/.config/Claude/claude_desktop_config.json``

    Claude Code stores its config at:

    * **macOS / Linux**: ``~/.claude.json`` (primary) or ``~/.claude/settings.json``
    * **Windows**: ``%USERPROFILE%\\.claude.json``

    ``config_path()`` returns the Desktop App path.  The ``discover_servers``
    method also checks the Claude Code locations.
    """

    tool_name = "claude_desktop"
    display_name = "Claude Desktop"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the platform-specific path to claude_desktop_config.json."""
        if sys.platform == "darwin":
            return (
                Path.home()
                / "Library"
                / "Application Support"
                / "Claude"
                / "claude_desktop_config.json"
            )
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    def _claude_code_paths(self) -> List[Path]:
        """Return candidate Claude Code config paths for the current platform."""
        if sys.platform == "win32":
            userprofile = os.environ.get("USERPROFILE", "")
            return [Path(userprofile) / ".claude.json"]
        return [
            Path.home() / ".claude.json",
            Path.home() / ".claude" / "settings.json",
        ]

    def read_config(self) -> Dict:
        """Read the Claude Desktop config JSON, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: Dict) -> None:
        """Write *data* to the Claude Desktop config file."""
        path = self.config_path()
        assert path is not None
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry in the Claude Desktop config."""
        data = self.read_config()
        data.setdefault("mcpServers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all MCP servers registered in Claude Desktop and Claude Code configs."""
        result: Dict[str, Dict] = self.read_config().get("mcpServers", {})
        # Also check Claude Code config files
        for path in self._claude_code_paths():
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.update(data.get("mcpServers", {}))
            except (json.JSONDecodeError, OSError):
                pass
        return result
