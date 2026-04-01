"""Adapter registry for all supported MCP config adapters."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Type

from src.multimcp.adapters.base import MCPConfigAdapter
from src.multimcp.adapters.tools.antigravity import AntigravityAdapter
from src.multimcp.adapters.tools.claude_desktop import ClaudeDesktopAdapter
from src.multimcp.adapters.tools.cline import ClineAdapter
from src.multimcp.adapters.tools.codex_cli import CodexCLIAdapter
from src.multimcp.adapters.tools.codex_desktop import CodexDesktopAdapter
from src.multimcp.adapters.tools.continue_dev import ContinueDevAdapter
from src.multimcp.adapters.tools.gemini_cli import GeminiCLIAdapter
from src.multimcp.adapters.tools.github_copilot import GitHubCopilotAdapter
from src.multimcp.adapters.tools.gptme import GptmeAdapter
from src.multimcp.adapters.tools.jetbrains import JetBrainsAdapter
from src.multimcp.adapters.tools.openclaw import OpenClawAdapter
from src.multimcp.adapters.tools.opencode import OpenCodeAdapter
from src.multimcp.adapters.tools.raycast import RaycastAdapter
from src.multimcp.adapters.tools.roo_code import RooCodeAdapter
from src.multimcp.adapters.tools.warp import WarpAdapter
from src.multimcp.adapters.tools.zed import ZedAdapter

# Canonical list of all adapter classes, sorted by tool_name for consistent ordering.
_ALL_ADAPTER_CLASSES: List[Type[MCPConfigAdapter]] = sorted(
    [
        AntigravityAdapter,
        ClaudeDesktopAdapter,
        ClineAdapter,
        CodexCLIAdapter,
        CodexDesktopAdapter,
        ContinueDevAdapter,
        GeminiCLIAdapter,
        GitHubCopilotAdapter,
        GptmeAdapter,
        JetBrainsAdapter,
        OpenClawAdapter,
        OpenCodeAdapter,
        RaycastAdapter,
        RooCodeAdapter,
        WarpAdapter,
        ZedAdapter,
    ],
    key=lambda cls: cls.tool_name,
)


class AdapterRegistry:
    """Registry that provides access to all built-in MCP config adapters."""

    def __init__(self, backup_dir: Optional[Path] = None):
        """Initialize the registry with all available adapters."""
        self._adapters: Dict[str, MCPConfigAdapter] = {}
        for cls in _ALL_ADAPTER_CLASSES:
            adapter = cls()
            if backup_dir is not None:
                adapter.backup_dir = backup_dir
            self._adapters[cls.tool_name] = adapter

    def all(self) -> List[MCPConfigAdapter]:
        """Return all adapters in alphabetical order by tool name."""
        return [self._adapters[name] for name in sorted(self._adapters)]

    def get(self, tool_name: str) -> Optional[MCPConfigAdapter]:
        """Return the adapter for *tool_name*, or None if not found."""
        return self._adapters.get(tool_name)