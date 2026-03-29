"""RetrievalPipeline — single entry point for tool filtering and ranking."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from mcp import types

from .base import ToolRetriever
from .logging import RetrievalLogger
from .models import RankingEvent, RetrievalConfig, ScoredTool
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

try:
    from .routing_tool import build_routing_tool_schema, ROUTING_TOOL_KEY
    _HAS_ROUTING_TOOL = True
except ImportError:
    _HAS_ROUTING_TOOL = False
    build_routing_tool_schema = None  # type: ignore[assignment]
    ROUTING_TOOL_KEY = None  # type: ignore[assignment]

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

        When disabled: returns ALL tools including cached/disconnected (client=None).
        When enabled: returns only tools in the session's active set, bounded by max_k.
        """
        if not self.config.enabled:
            return [m.tool for m in self.tool_registry.values()]

        t0 = time.monotonic()

        # Ensure session exists
        self.session_manager.get_or_create_session(session_id)
        active_keys = self.session_manager.get_active_tools(session_id)

        all_registry_keys = list(self.tool_registry.keys())

        if not active_keys:
            # Seed with top-K from full registry sorted by key (Phase 2 default)
            active_keys = set(sorted(all_registry_keys)[: self.config.max_k])

        # Enforce max_k bound
        max_k = self.config.max_k  # default 20
        active_keys_list = sorted(active_keys)[:max_k]

        # Build active mappings
        active_mappings = [
            (k, self.tool_registry[k])
            for k in active_keys_list
            if k in self.tool_registry
        ]

        # Compute demoted IDs (all registry keys NOT in active set)
        active_key_set = {k for k, _ in active_mappings}
        demoted_ids = [k for k in all_registry_keys if k not in active_key_set]

        # Tier 6 bounded fallback: if active_mappings is empty, use top-30 static defaults
        if not active_mappings:
            fallback_keys = sorted(all_registry_keys)[:30]
            active_mappings = [
                (k, self.tool_registry[k])
                for k in fallback_keys
                if k in self.tool_registry
            ]
            demoted_ids = []

        # Build routing tool schema (if enabled and there are demoted tools)
        routing_schema = None
        if self.config.enable_routing_tool and demoted_ids and _HAS_ROUTING_TOOL:
            routing_schema = build_routing_tool_schema(demoted_ids)

        # Build tool list from active mappings
        scored_tools = [
            ScoredTool(tool_key=k, tool_mapping=m, score=1.0)
            for k, m in active_mappings
        ]

        # Assemble with ranker+assembler if wired, else raw fallback
        if self.ranker is not None and self.assembler is not None:
            ranked = self.ranker.rank(scored_tools)
            result = self.assembler.assemble(
                ranked, self.config, routing_tool_schema=routing_schema
            )
        else:
            result = [m.tool for _, m in active_mappings]
            if routing_schema is not None:
                result.append(routing_schema)

        latency_ms = (time.monotonic() - t0) * 1000.0

        # Emit RankingEvent (OBS-02)
        event = RankingEvent(
            session_id=session_id,
            turn_number=0,  # Turn tracking is Phase 3; use 0 for now
            catalog_version="",
            active_k=len(active_mappings),
            fallback_tier=1,
            active_tool_ids=[k for k, _ in active_mappings],
            router_enum_size=len(demoted_ids),
            scorer_latency_ms=latency_ms,
        )
        await self.logger.log_ranking_event(event)

        return result

    def rebuild_catalog(self, registry: "dict[str, ToolMapping]") -> None:
        """Rebuild the retriever's index when the tool registry changes.

        Called by MCPProxyServer.register_client() and unregister_client()
        after any registry mutation (WIRE-02). No-op if retriever does not
        implement rebuild_index (e.g. PassthroughRetriever).
        """
        rebuild = getattr(self.retriever, "rebuild_index", None)
        if callable(rebuild):
            rebuild(registry)

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
