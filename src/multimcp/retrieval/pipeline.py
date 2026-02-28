"""RetrievalPipeline — single entry point for tool filtering and ranking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp import types

from .base import ToolRetriever
from .logging import RetrievalLogger
from .models import RetrievalConfig
from .session import SessionStateManager

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping


class RetrievalPipeline:
    """Orchestrates tool retrieval, ranking, and session state.

    When disabled: returns all tools (backward compatible).
    When enabled: returns session's active tool set (anchors + disclosed).
    """

    def __init__(
        self,
        retriever: ToolRetriever,
        session_manager: SessionStateManager,
        logger: RetrievalLogger,
        config: RetrievalConfig,
        tool_registry: dict[str, "ToolMapping"],
    ) -> None:
        self.retriever = retriever
        self.session_manager = session_manager
        self.logger = logger
        self.config = config
        self.tool_registry = tool_registry  # Reference, not copy

    async def get_tools_for_list(self, session_id: str) -> list[types.Tool]:
        """Called by _list_tools(). Returns tool list based on pipeline state.

        When disabled: returns all tools with connected clients (backward compat).
        When enabled: returns only tools in the session's active set.
        """
        if not self.config.enabled:
            return [m.tool for m in self.tool_registry.values() if m.client is not None]

        # Ensure session exists with anchor tools
        self.session_manager.get_or_create_session(session_id)
        active_keys = self.session_manager.get_active_tools(session_id)

        # Return tools matching active session keys
        tools = []
        for key in active_keys:
            mapping = self.tool_registry.get(key)
            if mapping and mapping.client is not None:
                tools.append(mapping.tool)
        return tools

    async def on_tool_called(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
    ) -> bool:
        """Called by _call_tool(). Placeholder for progressive disclosure.

        Returns True if new tools were disclosed (caller should send list_changed).
        Phase 3 stub — always returns False.
        """
        return False
