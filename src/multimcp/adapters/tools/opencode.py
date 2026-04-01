"""OpenCode MCP config adapter."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class OpenCodeAdapter(MCPConfigAdapter):
    """Adapter for the OpenCode AI assistant.

    OpenCode stores its full configuration (including MCP servers under the
    ``mcp`` key) in a platform-specific JSON or JSONC file:

    * **Linux / macOS**: ``~/.config/opencode/opencode.json``
    * **Windows**: ``%APPDATA%\\opencode\\opencode.jsonc``

    A project-level ``opencode.json`` in the current working directory is
    checked first; the user-level path is used as the fallback destination for
    writes when no project file exists.
    """

    tool_name = "opencode"
    display_name = "OpenCode"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def _user_config_path(self) -> Path:
        """Return the user-level OpenCode config path."""
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            return Path(appdata) / "opencode" / "opencode.jsonc" if appdata else Path.home() / "AppData" / "Roaming" / "opencode" / "opencode.jsonc"
        return Path.home() / ".config" / "opencode" / "opencode.json"

    def config_path(self) -> Optional[Path]:
        """Return the active OpenCode config path.

        Checks for a project-local ``opencode.json`` first; falls back to the
        user-level config path.
        """
        project = Path.cwd() / "opencode.json"
        if project.exists():
            return project
        return self._user_config_path()

    def _strip_jsonc_comments(self, content: str) -> str:
        """Strip single-line and multi-line comments from JSONC content."""
        # Remove single-line comments (// ...)
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        # Remove multi-line comments (/* ... */)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # Remove trailing commas before closing braces/brackets
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        return content

    def read_config(self) -> Dict:
        """Read OpenCode's config, returning {} if absent.

        Supports both JSON and JSONC formats (strips comments and trailing commas
        for .jsonc files or when JSONC markers are detected).
        """
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        content = path.read_text(encoding="utf-8")
        # Detect JSONC by file extension or content markers
        if path.suffix == ".jsonc" or "//" in content or "/*" in content:
            content = self._strip_jsonc_comments(content)
        return json.loads(content)

    def write_config(self, data: Dict) -> None:
        """Write *data* to OpenCode's config file."""
        path = self.config_path()
        assert path is not None
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcp`` key."""
        data = self.read_config()
        data.setdefault("mcp", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from OpenCode's ``mcp`` key."""
        return self.read_config().get("mcp", {})