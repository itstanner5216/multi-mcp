"""OpenClaw MCP config adapter.

Config files: JSON5
  Primary:  ~/.clawdbot/clawdbot.json5
  Fallback: ~/.config/clawdbot/clawdbot.json5

JSON5 is a superset of JSON that allows comments and trailing commas.
This adapter strips ``//`` line comments and ``/* */`` block comments before
parsing, then writes clean JSON (which is valid JSON5).  Pre-existing comments
in the file will be lost on write.

Schema (researched from https://docs.openclaw.ai/):
  {
    // OpenClaw config
    "mcpServers": {
      "<name>": {
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    }
  }

NOTE: https://docs.openclaw.ai/ and https://github.com/freema/openclaw-mcp were
inaccessible at build time; schema based on known community patterns.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


def _strip_json5_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` style comments from a JSON5 string.

    Uses a character-level state machine so that comment markers inside
    quoted strings (e.g. ``"https://example.com"`` or ``"use /* here */"``
    ) are never treated as comments.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape_next = False

    while i < n:
        ch = text[i]

        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue

        if in_string:
            if ch == "\\":
                escape_next = True
                result.append(ch)
            elif ch == '"':
                in_string = False
                result.append(ch)
            else:
                result.append(ch)
            i += 1
            continue

        # Outside a string
        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        # Block comment
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                break  # unclosed block comment — stop
            i = end + 2
            continue

        # Line comment
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i + 2)
            if end == -1:
                break  # comment runs to EOF
            i = end  # keep the newline
            continue

        result.append(ch)
        i += 1

    return "".join(result)


class OpenClawAdapter(MCPConfigAdapter):
    """Adapter for OpenClaw (~/.clawdbot/clawdbot.json5)."""

    tool_name = "openclaw"
    display_name = "OpenClaw"
    config_format = "json5"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the primary OpenClaw config file path."""
        return Path.home() / ".clawdbot" / "clawdbot.json5"

    def _fallback_path(self) -> Path:
        """Return the fallback OpenClaw config file path."""
        return Path.home() / ".config" / "clawdbot" / "clawdbot.json5"

    def _resolve_path(self) -> Path:
        """Return the first config path that exists, or the primary path."""
        primary = self.config_path()
        if primary is not None and primary.exists():
            return primary
        fallback = self._fallback_path()
        if fallback.exists():
            return fallback
        return primary  # type: ignore[return-value]

    def read_config(self) -> dict:
        """Read and parse the OpenClaw JSON5 config file."""
        path = self._resolve_path()
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        cleaned = _strip_json5_comments(raw)
        return json.loads(cleaned)

    def write_config(self, config: dict) -> None:
        """Write config dict to the OpenClaw config file as JSON."""
        path = self._resolve_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the OpenClaw config."""
        config = self.read_config()
        return dict(config.get("mcpServers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the OpenClaw MCP config."""
        config = self.read_config()
        config.setdefault("mcpServers", {})[server_name] = server_config
        self.write_config(config)
