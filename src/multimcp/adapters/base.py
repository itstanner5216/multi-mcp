"""Base class and platform utilities for MCP config adapters."""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional


def _current_platform() -> str:
    """Return a normalised platform string: 'macos', 'windows', or 'linux'."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


class MCPConfigAdapter(ABC):
    """Abstract base class for per-tool MCP configuration adapters.

    Each concrete subclass knows how to read and write the MCP server
    configuration for a specific AI tool (Claude Desktop, Zed, etc.).
    """

    tool_name: str
    display_name: str
    config_format: str  # "json" | "yaml" | "toml" | "json5"
    supported_platforms: List[str]

    def is_supported(self) -> bool:
        """Return True when this adapter is usable on the current platform."""
        return _current_platform() in self.supported_platforms

    @abstractmethod
    def config_path(self) -> Optional[Path]:
        """Return the path to the tool's MCP config file (or directory)."""

    @abstractmethod
    def read_config(self) -> Dict:
        """Read and return the current config as a plain dict."""

    @abstractmethod
    def write_config(self, data: Dict) -> None:
        """Persist *data* as the tool's config."""

    @abstractmethod
    def register_server(self, name: str, config: Dict) -> None:
        """Add or update an MCP server entry in the tool's config."""

    @abstractmethod
    def discover_servers(self) -> Dict[str, Dict]:
        """Return a mapping of server-name → server-config for this tool."""
