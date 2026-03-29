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
    from .routing_tool import build_routing_tool_schema
    _HAS_ROUTING_TOOL = True
except ImportError:
    _HAS_ROUTING_TOOL = False
    build_routing_tool_schema = None  # type: ignore[assignment]

try:
    from .rollout import get_session_group
except ImportError:
    def get_session_group(session_id: str, config: "RetrievalConfig") -> str:  # type: ignore[misc]
        return "control"

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping
    from .ranker import RelevanceRanker
    from .assembler import TieredAssembler


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
        # Master kill switch — enabled=False always returns all tools
        if not self.config.enabled:
            return [m.tool for m in self.tool_registry.values()]

        t0 = time.monotonic()

        # Determine session group for canary routing
        group = get_session_group(session_id, self.config)

        # Shadow mode: score but return all tools (backward compatible)
        # Control sessions in canary mode also get all tools
        is_filtered = (
            self.config.rollout_stage == "ga"
            or (self.config.rollout_stage == "canary" and group == "canary")
        )

        # Ensure session exists
        self.session_manager.get_or_create_session(session_id)
        active_keys = self.session_manager.get_active_tools(session_id)

        all_registry_keys = list(self.tool_registry.keys())

        # Dynamic K (FUSION-03): base 15, +3 if polyglot (max_k>17 proxy), cap at 20.
        polyglot_bonus = 3 if self.config.max_k > 17 else 0
        dynamic_k = min(20, max(15, self.config.max_k) + polyglot_bonus)
        if self.config.enable_routing_tool and _HAS_ROUTING_TOOL:
            direct_k = max(1, dynamic_k - 1)
        else:
            direct_k = dynamic_k

        if not active_keys:
            active_keys = set(sorted(all_registry_keys)[:self.config.max_k])

        active_keys_list = sorted(active_keys)[:direct_k]

        # Build active mappings
        active_mappings = [
            (k, self.tool_registry[k])
            for k in active_keys_list
            if k in self.tool_registry
        ]

        # Compute demoted IDs
        active_key_set = {k for k, _ in active_mappings}
        demoted_ids = [k for k in all_registry_keys if k not in active_key_set]

        # Tier 6 bounded fallback
        if not active_mappings:
            fallback_keys = sorted(all_registry_keys)[:30]
            active_mappings = [
                (k, self.tool_registry[k])
                for k in fallback_keys
                if k in self.tool_registry
            ]
            demoted_ids = []

        if is_filtered:
            # CANARY/GA: return bounded active set + routing tool
            routing_schema = None
            if self.config.enable_routing_tool and demoted_ids and _HAS_ROUTING_TOOL and build_routing_tool_schema is not None:
                routing_schema = build_routing_tool_schema(demoted_ids)

            scored_tools = [
                ScoredTool(tool_key=k, tool_mapping=m, score=1.0)
                for k, m in active_mappings
            ]

            if self.ranker is not None and self.assembler is not None:
                ranked = self.ranker.rank(scored_tools)
                result = self.assembler.assemble(
                    ranked, self.config, routing_tool_schema=routing_schema
                )
            else:
                result = [m.tool for _, m in active_mappings]
                if routing_schema is not None:
                    result.append(routing_schema)
        else:
            # SHADOW/CONTROL: return all tools (passthrough)
            result = [m.tool for m in self.tool_registry.values()]

        latency_ms = (time.monotonic() - t0) * 1000.0

        # Emit RankingEvent with group label (OBS-02)
        event = RankingEvent(
            session_id=session_id,
            turn_number=self._session_turns.get(session_id, 0),
            catalog_version="",
            active_k=len(active_mappings),
            fallback_tier=1,
            active_tool_ids=[k for k, _ in active_mappings],
            router_enum_size=len(demoted_ids),
            scorer_latency_ms=latency_ms,
            group=group,
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
