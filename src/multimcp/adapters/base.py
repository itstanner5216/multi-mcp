"""Abstract base class for per-tool MCP config adapters."""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class MCPConfigAdapter(ABC):
    """Abstract adapter that knows how to read/write MCP config for a specific tool.

    Each concrete subclass hard-codes the config file path(s), file format,
    and exact schema for one CLI/TUI/IDE.  No network I/O is performed at
    runtime; all schema knowledge is baked in at build time.
    """

    #: Short machine-readable identifier, e.g. ``"claude_desktop"``
    tool_name: str
    #: Human-readable label, e.g. ``"Claude Desktop"``
    display_name: str
    #: One of ``"json"``, ``"yaml"``, ``"toml"``, ``"json5"``
    config_format: str
    #: Platforms this adapter supports: subset of ``["macos", "linux", "windows"]``
    supported_platforms: list[str]

    @abstractmethod
    def config_path(self) -> Optional[Path]:
        """Return the resolved config file path for the current OS.

        Returns ``None`` when the current platform is not supported.
        """

    @abstractmethod
    def read_config(self) -> dict:
        """Read and parse the config file.

        Returns an empty ``dict`` when the file does not exist.
        """

    @abstractmethod
    def write_config(self, config: dict) -> None:
        """Write *config* back to the config file in the correct format."""

    @abstractmethod
    def discover_servers(self) -> dict[str, dict]:
        """Return all registered MCP servers as ``{server_name: server_config}``."""

    @abstractmethod
    def register_server(self, server_name: str, server_config: dict) -> None:
        """Add or update *server_name* in the config without corrupting existing entries."""

    def is_supported(self) -> bool:
        """Return ``True`` when the current platform is in :attr:`supported_platforms`."""
        platform = _current_platform()
        return platform in self.supported_platforms


def _current_platform() -> str:
    """Map ``sys.platform`` to one of ``"macos"``, ``"linux"``, or ``"windows"``."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"
