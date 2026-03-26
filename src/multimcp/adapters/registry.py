"""AdapterRegistry — discovers and indexes all per-tool MCP config adapters."""
from __future__ import annotations

from typing import Optional

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

_ALL_ADAPTER_CLASSES: list[type[MCPConfigAdapter]] = [
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
]


class AdapterRegistry:
    """Registry of all 16 per-tool MCP config adapters.

    Instantiates one adapter per tool and provides lookup by :attr:`tool_name`.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, MCPConfigAdapter] = {}
        for cls in _ALL_ADAPTER_CLASSES:
            adapter = cls()
            self._adapters[adapter.tool_name] = adapter

    def get(self, tool_name: str) -> Optional[MCPConfigAdapter]:
        """Return the adapter for *tool_name*, or ``None`` if not found."""
        return self._adapters.get(tool_name)

    def all(self) -> list[MCPConfigAdapter]:
        """Return all registered adapters, sorted by :attr:`tool_name`."""
        return sorted(self._adapters.values(), key=lambda a: a.tool_name)


# Module-level singleton — use this for all production code
_registry: Optional[AdapterRegistry] = None


def _get_registry() -> AdapterRegistry:
    """Return the module-level :class:`AdapterRegistry` singleton."""
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


def get_adapter(tool_name: str) -> Optional[MCPConfigAdapter]:
    """Return the adapter for *tool_name* from the global registry."""
    return _get_registry().get(tool_name)


def list_adapters() -> list[MCPConfigAdapter]:
    """Return all adapters from the global registry."""
    return _get_registry().all()
