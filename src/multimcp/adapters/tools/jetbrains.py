"""JetBrains IDEs MCP config adapter.

JetBrains AI Assistant (IntelliJ IDEA, PyCharm, etc.) can act as an MCP
**server** itself (exposing IDE capabilities to external AI agents), but it
also supports connecting to external MCP servers as a client.

Config file: JSON (per-IDE, per-version)
  The MCP client configuration is stored in the IDE's settings XML files
  located at:
    macOS:   ~/Library/Application Support/JetBrains/<ProductVersion>/options/mcp.xml
    Linux:   ~/.config/JetBrains/<ProductVersion>/options/mcp.xml
    Windows: %APPDATA%\\JetBrains\\<ProductVersion>\\options\\mcp.xml

  Because the product name and version vary (e.g. "IntelliJIdea2024.3",
  "PyCharm2024.3"), this adapter scans for any matching ``mcp.xml`` file
  under the JetBrains config root.

  The mcp.xml format is an IntelliJ-style XML component file; MCP server
  entries are stored in a JSON-encoded string attribute.  Community tooling
  typically manages this via the IDE UI rather than direct file editing.

  This adapter provides best-effort support:
  - ``discover_servers`` scans for ``mcp.xml`` files and returns whatever
    it can parse.
  - ``register_server`` logs a warning and raises ``NotImplementedError``
    because the XML/binary format is IDE-managed and direct file mutation
    risks corrupting IDE state.

NOTE: https://www.jetbrains.com/help/ai-assistant/mcp.html was inaccessible
at build time; behaviour documented from known community patterns.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from src.multimcp.adapters.base import MCPConfigAdapter


class JetBrainsAdapter(MCPConfigAdapter):
    """Read-only adapter for JetBrains IDE MCP configuration.

    Direct write support is not implemented because JetBrains uses an
    IDE-managed XML format.  Use the IDE's built-in AI Assistant settings
    UI to register MCP servers.
    """

    tool_name = "jetbrains"
    display_name = "JetBrains IDEs"
    config_format = "json"
    supported_platforms = ["macos", "linux", "windows"]

    def _jetbrains_root(self) -> Optional[Path]:
        """Return the JetBrains config root directory for the current OS."""
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "JetBrains"
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                return None
            return Path(appdata) / "JetBrains"
        # Linux / XDG
        return Path.home() / ".config" / "JetBrains"

    def config_path(self) -> Optional[Path]:
        """Return the JetBrains config root (not a single file).

        Returns ``None`` on unsupported platforms.
        """
        return self._jetbrains_root()

    def read_config(self) -> dict:
        """Scan for JetBrains MCP XML config files and return raw paths.

        Returns a dict of ``{"<ProductVersion>": "<path_to_mcp.xml>"}`` for
        any IDE installs found.  Full XML parsing is not implemented.
        """
        root = self._jetbrains_root()
        if root is None or not root.exists():
            return {}
        result: dict = {}
        for mcp_xml in root.glob("*/options/mcp.xml"):
            product_version = mcp_xml.parts[-3]  # e.g. "IntelliJIdea2024.3"
            result[product_version] = str(mcp_xml)
        return result

    def write_config(self, config: dict) -> None:
        """Not implemented — JetBrains config is managed by the IDE itself."""
        raise NotImplementedError(
            f"{self.display_name}: direct config write is not supported. "
            "Use the IDE's AI Assistant settings UI to manage MCP servers."
        )

    def discover_servers(self) -> dict[str, dict]:
        """Return any JetBrains MCP config file locations found on disk.

        Full server-entry parsing is not implemented due to the proprietary
        XML format.  Returns ``{"<product>": {"config_file": "<path>"}}``
        for any installs discovered.
        """
        raw = self.read_config()
        return {product: {"config_file": path} for product, path in raw.items()}

    def register_server(self, server_name: str, server_config: dict) -> None:
        """Not implemented — use JetBrains AI Assistant settings UI."""
        raise NotImplementedError(
            f"{self.display_name}: direct server registration is not supported. "
            "Use the IDE's AI Assistant settings UI under "
            "Settings → Tools → AI Assistant → MCP Servers."
        )
