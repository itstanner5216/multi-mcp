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

try:
    from .fusion import weighted_rrf, compute_alpha
    _HAS_FUSION = True
except ImportError:
    _HAS_FUSION = False
    weighted_rrf = None  # type: ignore[assignment]
    compute_alpha = None  # type: ignore[assignment]

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
        self._session_turns: dict[str, int] = {}  # session_id -> current turn number

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

        # Dynamic K (FUSION-03): base 15, +3 if polyglot (max_k>17 proxy), cap at 20.
        # Routing tool is counted within dynamic_k (reserve 1 slot when routing enabled).
        polyglot_bonus = 3 if self.config.max_k > 17 else 0
        dynamic_k = min(20, max(15, self.config.max_k) + polyglot_bonus)
        # Reserve one slot for the routing tool so total(direct + routing) <= dynamic_k
        if self.config.enable_routing_tool and _HAS_ROUTING_TOOL:
            direct_k = max(1, dynamic_k - 1)
        else:
            direct_k = dynamic_k

        if not active_keys:
            # Fresh session: seed with raw config.max_k (not the floor) so that
            # explicit small K values are respected for initial tool exposure.
            active_keys = set(sorted(all_registry_keys)[:self.config.max_k])

        active_keys_list = sorted(active_keys)[:direct_k]

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
            turn_number=self._session_turns.get(session_id, 0),
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
        """Called by _call_tool(). Tracks turns and triggers promote/demote evaluation.

        Returns True if active set changed (caller should send list_changed notification).
        """
        if not self.config.enabled:
            return False

        # Increment turn counter for this session
        self._session_turns[session_id] = self._session_turns.get(session_id, 0) + 1

        # Record tool usage for demote safety (used_this_turn)
        # Demote evaluation is delegated to pipeline on the NEXT turn boundary
        # For now: disclose any new tools based on what was called (promote via usage signal)
        if hasattr(self.session_manager, 'promote') and tool_name in self.tool_registry:
            newly_added = self.session_manager.promote(session_id, [tool_name])
            return len(newly_added) > 0

        return False
