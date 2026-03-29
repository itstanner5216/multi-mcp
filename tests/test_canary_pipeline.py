"""Tests for canary rollout routing in RetrievalPipeline (Phase 4)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.models import RankingEvent, RetrievalConfig
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.session import SessionStateManager


class _CapturingLogger(NullLogger):
    """Logger that captures RankingEvents for assertion."""

    def __init__(self) -> None:
        self.events: list[RankingEvent] = []

    async def log_ranking_event(self, event: RankingEvent) -> None:
        self.events.append(event)


def _make_tool(name: str, server: str = "test") -> MagicMock:
    """Create a mock ToolMapping."""
    tool = MagicMock()
    tool.name = name
    tool.description = f"Test tool {name}"
    tool.inputSchema = {"type": "object", "properties": {}}
    mapping = MagicMock()
    mapping.tool = tool
    mapping.server_name = server
    return mapping


def _build_registry(n: int = 25) -> dict[str, MagicMock]:
    """Build a registry of n tools."""
    registry: dict[str, MagicMock] = {}
    for i in range(n):
        key = f"test__tool_{i:02d}"
        registry[key] = _make_tool(f"tool_{i:02d}")
    return registry


def _make_pipeline(
    registry: dict[str, MagicMock],
    logger: NullLogger | _CapturingLogger | None = None,
    **config_kwargs: object,
) -> RetrievalPipeline:
    config = RetrievalConfig(**config_kwargs)  # type: ignore[arg-type]
    return RetrievalPipeline(
        retriever=PassthroughRetriever(),
        session_manager=SessionStateManager(config),
        logger=logger or NullLogger(),
        config=config,
        tool_registry=registry,
    )


class TestShadowStage:
    @pytest.mark.asyncio
    async def test_shadow_returns_all_tools(self) -> None:
        registry = _build_registry(25)
        pipe = _make_pipeline(registry, enabled=True, rollout_stage="shadow")
        tools = await pipe.get_tools_for_list("session-1")
        assert len(tools) == 25

    @pytest.mark.asyncio
    async def test_shadow_group_is_control(self) -> None:
        registry = _build_registry(25)
        logger = _CapturingLogger()
        pipe = _make_pipeline(registry, logger=logger, enabled=True, rollout_stage="shadow")
        await pipe.get_tools_for_list("session-1")
        assert logger.events[0].group == "control"


class TestCanaryStage:
    @pytest.mark.asyncio
    async def test_canary_zero_percent_returns_all(self) -> None:
        registry = _build_registry(25)
        pipe = _make_pipeline(
            registry, enabled=True, rollout_stage="canary", canary_percentage=0.0
        )
        tools = await pipe.get_tools_for_list("session-1")
        assert len(tools) == 25

    @pytest.mark.asyncio
    async def test_canary_hundred_percent_returns_filtered(self) -> None:
        registry = _build_registry(25)
        pipe = _make_pipeline(
            registry, enabled=True, rollout_stage="canary", canary_percentage=100.0,
            max_k=15,
        )
        tools = await pipe.get_tools_for_list("session-1")
        # Should be bounded: direct_k tools + optional routing tool
        assert len(tools) <= 20  # dynamic_k cap

    @pytest.mark.asyncio
    async def test_canary_mixed_groups(self) -> None:
        registry = _build_registry(25)
        logger = _CapturingLogger()
        pipe = _make_pipeline(
            registry, logger=logger, enabled=True, rollout_stage="canary",
            canary_percentage=50.0, max_k=15,
        )
        groups = set()
        tool_counts = set()
        for i in range(50):
            tools = await pipe.get_tools_for_list(f"session-{i}")
            groups.add(logger.events[-1].group)
            tool_counts.add(len(tools))
        # With 50 sessions at 50%, should see both groups
        assert "canary" in groups
        assert "control" in groups
        # Should see different tool counts (filtered vs all)
        assert len(tool_counts) >= 2


class TestGAStage:
    @pytest.mark.asyncio
    async def test_ga_all_sessions_filtered(self) -> None:
        registry = _build_registry(25)
        pipe = _make_pipeline(
            registry, enabled=True, rollout_stage="ga", max_k=15,
        )
        for i in range(10):
            tools = await pipe.get_tools_for_list(f"session-{i}")
            assert len(tools) <= 20

    @pytest.mark.asyncio
    async def test_ga_group_is_canary(self) -> None:
        registry = _build_registry(25)
        logger = _CapturingLogger()
        pipe = _make_pipeline(
            registry, logger=logger, enabled=True, rollout_stage="ga",
        )
        await pipe.get_tools_for_list("session-1")
        assert logger.events[0].group == "canary"


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_disabled_overrides_ga(self) -> None:
        registry = _build_registry(25)
        pipe = _make_pipeline(registry, enabled=False, rollout_stage="ga")
        tools = await pipe.get_tools_for_list("session-1")
        assert len(tools) == 25

    @pytest.mark.asyncio
    async def test_disabled_overrides_canary(self) -> None:
        registry = _build_registry(25)
        pipe = _make_pipeline(
            registry, enabled=False, rollout_stage="canary", canary_percentage=100.0,
        )
        tools = await pipe.get_tools_for_list("session-1")
        assert len(tools) == 25


class TestRankingEventGroup:
    @pytest.mark.asyncio
    async def test_event_group_matches_assignment(self) -> None:
        registry = _build_registry(25)
        logger = _CapturingLogger()
        pipe = _make_pipeline(
            registry, logger=logger, enabled=True, rollout_stage="canary",
            canary_percentage=50.0,
        )
        for i in range(20):
            await pipe.get_tools_for_list(f"s-{i}")
        groups = {ev.group for ev in logger.events}
        assert groups.issubset({"canary", "control"})
