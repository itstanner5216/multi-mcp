"""OpenClaw MCP config adapter with JSON5 comment stripping."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional

from src.multimcp.adapters.base import MCPConfigAdapter


def _strip_json5_comments(text: str) -> str:
    """Remove ``//`` line comments and ``/* */`` block comments from *text*.

    String literals are preserved – comments inside strings are not stripped.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # String literal – copy verbatim, handling escape sequences
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            result.append(text[i:j])
            i = j
        # Line comment
        elif text[i : i + 2] == "//":
            j = i + 2
            while j < n and text[j] != "\n":
                j += 1
            # Keep the newline that terminates the comment
            i = j
        # Block comment
        elif text[i : i + 2] == "/*":
            j = i + 2
            while j < n - 1 and text[j : j + 2] != "*/":
                j += 1
            i = j + 2
        else:
            result.append(ch)
            i += 1
    return "".join(result)


class OpenClawAdapter(MCPConfigAdapter):
    """Adapter for the OpenClaw AI assistant (uses JSON5 config)."""

    tool_name = "openclaw"
    display_name = "OpenClaw"
    config_format = "json5"
    supported_platforms = ["macos", "linux", "windows"]

    def _resolve_path(self) -> Path:
        """Return the default path to OpenClaw's config file."""
        return Path.home() / ".openclaw" / "openclaw.json"

    def config_path(self) -> Optional[Path]:
        """Return the path to OpenClaw's JSON5 config file."""
        return self._resolve_path()

    def read_config(self) -> Dict:
        """Read and parse the JSON5 config, stripping comments.

        Returns {} if the file does not exist.
        """
        path = self._resolve_path()
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        clean = _strip_json5_comments(raw)
        return json.loads(clean)

    def write_config(self, data: Dict) -> None:
        """Write *data* as plain JSON to the OpenClaw config file."""
        path = self._resolve_path()
        self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry under the ``mcpServers`` key."""
        data = self.read_config()
        data.setdefault("mcpServers", {})[name] = config
        self.write_config(data)

    def discover_servers(self) -> Dict[str, Dict]:
        """Return all servers from OpenClaw's ``mcpServers`` key."""
        return self.read_config().get("mcpServers", {})
