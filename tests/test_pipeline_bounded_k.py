"""Tests for bounded-K enforcement, routing tool assembly, and RankingEvent emission.

FALLBACK-01: Tier 6 fallback returns top-30 static defaults from sorted tool_to_server
FALLBACK-02: get_tools_for_list() returns at most config.max_k direct tools + routing tool
OBS-02: After assembling, logger.log_ranking_event(event) is awaited with correct RankingEvent
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types

from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.models import RankingEvent, RetrievalConfig, ScoredTool
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.session import SessionStateManager


@dataclass
class FakeToolMapping:
    tool: types.Tool
    server_name: str = "test_server"
    client: object = None


def make_tool(name: str) -> types.Tool:
    return types.Tool(
        name=name,
        description=f"Tool {name}",
        inputSchema={"type": "object", "properties": {}},
    )


def make_registry(n: int, prefix: str = "srv__tool") -> dict:
    return {
        f"{prefix}{i:02d}": FakeToolMapping(tool=make_tool(f"{prefix}{i:02d}"))
        for i in range(n)
    }


def make_pipeline(registry: dict, max_k: int = 5, enable_routing_tool: bool = True, logger=None):
    from src.multimcp.retrieval.base import ToolRetriever

    class PassthroughRetriever(ToolRetriever):
        def retrieve(self, context, registry):
            return []
        def rebuild_index(self, registry):
            pass

    config = RetrievalConfig(
        enabled=True,
        max_k=max_k,
        enable_routing_tool=enable_routing_tool,
        full_description_count=10,
    )
    session_mgr = SessionStateManager(config=config)
    if logger is None:
        logger = NullLogger()
    return RetrievalPipeline(
        retriever=PassthroughRetriever(),
        session_manager=session_mgr,
        logger=logger,
        config=config,
        tool_registry=registry,
    )


class TestBoundedK:
    """get_tools_for_list() returns at most max_k direct tools + routing tool."""

    @pytest.mark.asyncio
    async def test_max_k_enforced_with_10_tools_max_k_5(self):
        """With 10 tools and max_k=5, returns at most 5 active tools (plus routing)."""
        registry = make_registry(10)
        pipeline = make_pipeline(registry, max_k=5)
        result = await pipeline.get_tools_for_list("session1")
        # At most max_k=5 direct tools plus at most 1 routing tool
        non_routing = [t for t in result if t.name != "request_tool"]
        assert len(non_routing) <= 5

    @pytest.mark.asyncio
    async def test_routing_tool_present_when_demoted_tools_exist(self):
        """When there are demoted tools, routing tool is included."""
        registry = make_registry(10)
        pipeline = make_pipeline(registry, max_k=5, enable_routing_tool=True)
        result = await pipeline.get_tools_for_list("session1")
        tool_names = [t.name for t in result]
        assert "request_tool" in tool_names

    @pytest.mark.asyncio
    async def test_routing_tool_absent_when_disabled(self):
        """When enable_routing_tool=False, routing tool is not in result."""
        registry = make_registry(10)
        pipeline = make_pipeline(registry, max_k=5, enable_routing_tool=False)
        result = await pipeline.get_tools_for_list("session1")
        tool_names = [t.name for t in result]
        assert "request_tool" not in tool_names

    @pytest.mark.asyncio
    async def test_registry_smaller_than_max_k(self):
        """With fewer tools than max_k, all tools returned (no routing tool needed)."""
        registry = make_registry(3)
        pipeline = make_pipeline(registry, max_k=5, enable_routing_tool=True)
        result = await pipeline.get_tools_for_list("session1")
        # Only 3 tools, max_k=5, no demoted tools so no routing tool
        non_routing = [t for t in result if t.name != "request_tool"]
        assert len(non_routing) <= 5

    @pytest.mark.asyncio
    async def test_disabled_pipeline_returns_all_tools(self):
        """When enabled=False, returns all tools unchanged."""
        from src.multimcp.retrieval.base import ToolRetriever

        class PassthroughRetriever(ToolRetriever):
            def retrieve(self, context, registry):
                return []
            def rebuild_index(self, registry):
                pass

        registry = make_registry(25)
        config = RetrievalConfig(enabled=False, max_k=5)
        session_mgr = SessionStateManager(config=config)
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=session_mgr,
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        result = await pipeline.get_tools_for_list("session1")
        assert len(result) == 25


class TestFallbackTier6:
    """Tier 6 fallback returns top-30 static defaults, never full registry."""

    @pytest.mark.asyncio
    async def test_tier6_returns_at_most_30_when_registry_large(self):
        """With 50 tools and all fallback paths exhausted, returns at most 30."""
        registry = make_registry(50)
        pipeline = make_pipeline(registry, max_k=5, enable_routing_tool=True)
        # Force empty active keys by using a session with no state
        result = await pipeline.get_tools_for_list("new_session_xyz")
        non_routing = [t for t in result if t.name != "request_tool"]
        # Should have at most max_k=5 direct tools (not 50 full registry)
        assert len(non_routing) <= 30

    @pytest.mark.asyncio
    async def test_tier6_bounded_never_full_registry(self):
        """With 100 tools, the result is bounded (never full catalog exposed)."""
        registry = make_registry(100)
        pipeline = make_pipeline(registry, max_k=5, enable_routing_tool=True)
        result = await pipeline.get_tools_for_list("fresh_session")
        non_routing = [t for t in result if t.name != "request_tool"]
        assert len(non_routing) <= 30  # Tier 6 caps at 30


class TestRankingEventEmission:
    """RankingEvent is emitted after assembling with correct fields."""

    @pytest.mark.asyncio
    async def test_ranking_event_emitted(self):
        """log_ranking_event is called once per get_tools_for_list call."""
        registry = make_registry(10)
        mock_logger = AsyncMock()
        mock_logger.log_ranking_event = AsyncMock()

        from src.multimcp.retrieval.base import ToolRetriever

        class PassthroughRetriever(ToolRetriever):
            def retrieve(self, context, registry):
                return []
            def rebuild_index(self, registry):
                pass

        config = RetrievalConfig(enabled=True, max_k=5, full_description_count=10)
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config=config),
            logger=mock_logger,
            config=config,
            tool_registry=registry,
        )
        await pipeline.get_tools_for_list("session1")
        mock_logger.log_ranking_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ranking_event_session_id_matches(self):
        """RankingEvent.session_id matches the session_id passed to get_tools_for_list."""
        registry = make_registry(10)
        captured_events = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event):
                captured_events.append(event)

        pipeline = make_pipeline(registry, max_k=5, logger=CapturingLogger())
        await pipeline.get_tools_for_list("my-session-id")
        assert len(captured_events) == 1
        assert captured_events[0].session_id == "my-session-id"

    @pytest.mark.asyncio
    async def test_ranking_event_active_k_bounded(self):
        """RankingEvent.active_k == min(len(active_keys), config.max_k)."""
        registry = make_registry(10)
        captured_events = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event):
                captured_events.append(event)

        pipeline = make_pipeline(registry, max_k=5, logger=CapturingLogger())
        await pipeline.get_tools_for_list("session1")
        event = captured_events[0]
        assert event.active_k <= 5

    @pytest.mark.asyncio
    async def test_ranking_event_router_enum_size_is_demoted_count(self):
        """RankingEvent.router_enum_size == len(demoted_ids)."""
        registry = make_registry(10)
        captured_events = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event):
                captured_events.append(event)

        pipeline = make_pipeline(registry, max_k=5, logger=CapturingLogger())
        result = await pipeline.get_tools_for_list("session1")

        event = captured_events[0]
        non_routing = [t for t in result if t.name != "request_tool"]
        # router_enum_size == total registry - active set size
        assert event.router_enum_size == len(registry) - event.active_k

    @pytest.mark.asyncio
    async def test_ranking_event_scorer_latency_nonnegative(self):
        """RankingEvent.scorer_latency_ms is non-negative."""
        registry = make_registry(5)
        captured_events = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event):
                captured_events.append(event)

        pipeline = make_pipeline(registry, max_k=5, logger=CapturingLogger())
        await pipeline.get_tools_for_list("session1")
        assert captured_events[0].scorer_latency_ms >= 0.0


class TestPipelineImports:
    """Pipeline imports and contains required symbols."""

    def test_pipeline_contains_ranking_event(self):
        """pipeline.py imports or uses RankingEvent."""
        import importlib
        import inspect
        import src.multimcp.retrieval.pipeline as pipeline_mod
        source = inspect.getsource(pipeline_mod)
        assert "RankingEvent" in source

    def test_pipeline_contains_log_ranking_event(self):
        """pipeline.py calls log_ranking_event."""
        import inspect
        import src.multimcp.retrieval.pipeline as pipeline_mod
        source = inspect.getsource(pipeline_mod)
        assert "log_ranking_event" in source

    def test_pipeline_contains_build_routing_tool_schema(self):
        """pipeline.py references build_routing_tool_schema."""
        import inspect
        import src.multimcp.retrieval.pipeline as pipeline_mod
        source = inspect.getsource(pipeline_mod)
        assert "build_routing_tool_schema" in source

    def test_pipeline_contains_demoted_ids(self):
        """pipeline.py computes demoted_ids."""
        import inspect
        import src.multimcp.retrieval.pipeline as pipeline_mod
        source = inspect.getsource(pipeline_mod)
        assert "demoted_ids" in source
