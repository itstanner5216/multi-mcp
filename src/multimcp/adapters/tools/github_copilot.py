"""GitHub Copilot (VS Code) MCP config adapter.

Config file: JSON
  VS Code workspace: .vscode/mcp.json
  User-level:        <vscode-user-data>/User/mcp.json

This adapter targets .vscode/mcp.json in the current working directory, which
is the standard way to configure Copilot MCP servers per project.

Schema (researched from https://code.visualstudio.com/docs/copilot/customization/mcp-servers):
  {
    "servers": {
      "<name>": {
        "type": "stdio",
        "command": "<executable>",
        "args": ["<arg1>", ...],
        "env": { "KEY": "value" }
      }
    }
  }
  SSE variant uses "type": "sse" and "url": "http://..." instead of command/args.

NOTE: https://code.visualstudio.com/docs/copilot/customization/mcp-servers was
inaccessible at build time; schema based on known community patterns and VS Code
public documentation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class GitHubCopilotAdapter(MCPConfigAdapter):
    """Adapter for GitHub Copilot in VS Code (.vscode/mcp.json)."""

    tool_name = "github_copilot"
    display_name = "GitHub Copilot (VS Code)"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def config_path(self) -> Optional[Path]:
        """Return the VS Code workspace MCP config file path."""
        return Path.cwd() / ".vscode" / "mcp.json"

    def read_config(self) -> dict:
        """Read and parse the VS Code MCP JSON config file."""
        path = self.config_path()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def write_config(self, config: dict) -> None:
        """Write config dict back to the VS Code MCP JSON config file."""
        path = self.config_path()
        if path is None:
            raise RuntimeError(f"{self.display_name}: unsupported platform")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")

    def discover_servers(self) -> dict[str, dict]:
        """Return all MCP servers registered in the VS Code Copilot config."""
        config = self.read_config()
        return dict(config.get("servers", {}))

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the VS Code Copilot MCP config.

        *server_config* should include ``"type"``, ``"command"``/``"args"``/``"env"``
        (stdio) or ``"type"`` and ``"url"`` (SSE).
        """
        config = self.read_config()
        config.setdefault("servers", {})[server_name] = server_config
        self.write_config(config)
