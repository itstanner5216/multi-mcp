"""Claude Desktop MCP config adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from src.multimcp.adapters.base import MCPConfigAdapter
from src.utils.logger import get_logger

logger = get_logger(__name__)


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
            userprofile = os.environ.get("USERPROFILE")
            base = Path(userprofile) if userprofile else Path.home()
            return [base / ".claude.json"]
        return [
            Path.home() / ".claude.json",
            Path.home() / ".claude" / "settings.json",
        ]

    def read_config(self) -> Dict:
        """Read the Claude Desktop config JSON, returning {} if absent."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Config at {path} is not valid JSON ({e}), using empty config")
            return {}
        if not isinstance(data, dict):
            logger.warning(
                f"Config at {path} returned non-dict data ({type(data).__name__}), using empty config"
            )
            return {}
        return data

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
        existing_mcp = data.get("mcpServers", {})
        if not isinstance(existing_mcp, dict):
            logger.warning(
                f"mcpServers key contains non-dict value ({type(existing_mcp).__name__}), replacing with empty dict"
            )
            existing_mcp = {}
        existing_mcp[name] = config
        data["mcpServers"] = existing_mcp
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all MCP servers registered in Claude Desktop and Claude Code configs.

        Note: Claude Code entries take precedence over Claude Desktop entries with the
        same name. Any overwrites are logged for visibility.
        """
        raw_mcp = self.read_config().get("mcpServers", {})
        if not isinstance(raw_mcp, dict):
            logger.warning(
                f"mcpServers key contains non-dict value ({type(raw_mcp).__name__}), using empty dict"
            )
            raw_mcp = {}
        result: Dict[str, Dict] = raw_mcp
        # Also check Claude Code config files
        for path in self._claude_code_paths():
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    mcp_servers = data.get("mcpServers")
                    if isinstance(mcp_servers, dict):
                        # Handle key collisions explicitly
                        for server_name, server_config in mcp_servers.items():
                            if server_name in result:
                                logger.warning(
                                    f"Server '{server_name}' from Claude Code config ({path}) "
                                    f"overwrites entry from Claude Desktop config"
                                )
                            result[server_name] = server_config
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse Claude Code config at {path}: {e}"
                )
            except OSError as e:
                logger.error(
                    f"Failed to read Claude Code config at {path}: {e}"
                )
        return result