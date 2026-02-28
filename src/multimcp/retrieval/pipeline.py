"""RetrievalPipeline — single entry point for tool filtering and ranking."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from mcp import types

from .base import ToolRetriever
from .logging import RetrievalLogger
from .models import RetrievalConfig, ScoredTool
from .session import SessionStateManager

# Optional imports — these are injected when wiring is complete
try:
    from .ranker import RelevanceRanker
except ImportError:
    RelevanceRanker = None  # type: ignore[assignment,misc]

try:
    from .assembler import TieredAssembler
except ImportError:
    TieredAssembler = None  # type: ignore[assignment,misc]

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
        ranker: Optional["RelevanceRanker"] = None,
        assembler: Optional["TieredAssembler"] = None,
    ) -> None:
        self.retriever = retriever
        self.session_manager = session_manager
        self.logger = logger
        self.config = config
        self.tool_registry = tool_registry  # Reference, not copy
        self.ranker = ranker
        self.assembler = assembler

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

        # Build tool list from active session keys
        active_mappings = []
        for key in active_keys:
            mapping = self.tool_registry.get(key)
            if mapping and mapping.client is not None:
                active_mappings.append((key, mapping))

        # If ranker and assembler are wired, use full pipeline
        if self.ranker is not None and self.assembler is not None:
            scored_tools = [
                ScoredTool(tool_key=key, tool_mapping=mapping, score=1.0)
                for key, mapping in active_mappings
            ]
            ranked = self.ranker.rank(scored_tools)
            return self.assembler.assemble(ranked, self.config)

        # Fallback: return raw Tool objects without ranking/tiering
        return [mapping.tool for _, mapping in active_mappings]

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
