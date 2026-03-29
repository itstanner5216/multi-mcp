"""Tests for Phase 3 pipeline changes: turn tracking, dynamic K, and fusion wiring.

TDD RED tests — written before implementation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp import types

from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import RetrievalConfig


def _make_tool(name: str, desc: str = "A tool") -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": {}},
    )


def _make_mapping(server: str, tool: types.Tool):
    """Create a mock ToolMapping."""
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()
    return m


def _make_pipeline(
    registry: dict | None = None,
    config: RetrievalConfig | None = None,
) -> RetrievalPipeline:
    if config is None:
        config = RetrievalConfig(enabled=True, max_k=20)
    if registry is None:
        registry = {}
    return RetrievalPipeline(
        retriever=PassthroughRetriever(),
        session_manager=SessionStateManager(config),
        logger=NullLogger(),
        config=config,
        tool_registry=registry,
    )


class TestTurnTracking:
    """Turn counter increments on each on_tool_called()."""

    @pytest.mark.asyncio
    async def test_session_turns_initializes_to_zero(self):
        """New pipeline has no turn tracking entries."""
        p = _make_pipeline()
        # _session_turns should be a dict attribute
        assert hasattr(p, "_session_turns")
        assert p._session_turns == {}

    @pytest.mark.asyncio
    async def test_on_tool_called_increments_turn_counter(self):
        """Each call increments the turn counter for the session."""
        p = _make_pipeline()
        await p.on_tool_called("sess-1", "some_tool", {})
        assert p._session_turns.get("sess-1", 0) == 1

    @pytest.mark.asyncio
    async def test_on_tool_called_multiple_increments(self):
        """Multiple calls increment the counter correctly."""
        p = _make_pipeline()
        for _ in range(3):
            await p.on_tool_called("sess-1", "some_tool", {})
        assert p._session_turns.get("sess-1", 0) == 3

    @pytest.mark.asyncio
    async def test_on_tool_called_sessions_independent(self):
        """Turn counters are independent per session."""
        p = _make_pipeline()
        await p.on_tool_called("sess-1", "tool_a", {})
        await p.on_tool_called("sess-1", "tool_a", {})
        await p.on_tool_called("sess-2", "tool_b", {})
        assert p._session_turns.get("sess-1", 0) == 2
        assert p._session_turns.get("sess-2", 0) == 1

    @pytest.mark.asyncio
    async def test_on_tool_called_disabled_no_increment(self):
        """When pipeline is disabled, on_tool_called returns False immediately, no tracking."""
        p = _make_pipeline(config=RetrievalConfig(enabled=False))
        result = await p.on_tool_called("sess-1", "tool", {})
        assert result is False
        assert p._session_turns.get("sess-1", 0) == 0


class TestOnToolCalledPromote:
    """on_tool_called triggers promote() when tool is known."""

    @pytest.mark.asyncio
    async def test_returns_false_when_tool_not_in_registry(self):
        """Unknown tool: no promote, return False."""
        p = _make_pipeline(registry={})
        p.session_manager.get_or_create_session("s1")
        result = await p.on_tool_called("s1", "unknown_tool", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_tool_already_active(self):
        """Tool already in active set: promote returns empty, return False."""
        tool = _make_tool("existing_tool")
        registry = {"github__existing_tool": _make_mapping("github", tool)}
        p = _make_pipeline(registry=registry)
        # Create session with the tool already active
        p.session_manager.get_or_create_session("s1")
        p.session_manager.add_tools("s1", ["github__existing_tool"])
        result = await p.on_tool_called("s1", "github__existing_tool", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_new_tool_promoted(self):
        """Tool in registry but not yet active: promote returns it, return True."""
        tool = _make_tool("new_tool")
        registry = {"github__new_tool": _make_mapping("github", tool)}
        p = _make_pipeline(registry=registry)
        # Create session WITHOUT the tool
        p.session_manager.get_or_create_session("s1")
        result = await p.on_tool_called("s1", "github__new_tool", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_turn_increments_even_without_promotion(self):
        """Turn counter increments regardless of whether promotion happens."""
        p = _make_pipeline(registry={})
        p.session_manager.get_or_create_session("s1")
        await p.on_tool_called("s1", "missing_tool", {})
        assert p._session_turns.get("s1", 0) == 1


class TestRankingEventTurnNumber:
    """RankingEvent.turn_number uses real turn count (not hardcoded 0)."""

    @pytest.mark.asyncio
    async def test_ranking_event_turn_number_zero_initially(self):
        """On first get_tools_for_list call, turn_number = 0 (no calls yet)."""
        config = RetrievalConfig(enabled=True, max_k=5)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(5)
        }
        logger = NullLogger()
        logged_events = []
        original_log = logger.log_ranking_event

        async def capture_event(event):
            logged_events.append(event)
            return await original_log(event)

        logger.log_ranking_event = capture_event  # type: ignore[method-assign]

        p = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=logger,
            config=config,
            tool_registry=registry,
        )
        await p.get_tools_for_list("s1")
        assert len(logged_events) == 1
        assert logged_events[0].turn_number == 0  # No on_tool_called yet

    @pytest.mark.asyncio
    async def test_ranking_event_turn_number_reflects_actual_turn(self):
        """After two on_tool_called(), get_tools_for_list emits turn_number=2."""
        config = RetrievalConfig(enabled=True, max_k=5)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(5)
        }
        logger = NullLogger()
        logged_events = []

        async def capture_event(event):
            logged_events.append(event)

        logger.log_ranking_event = capture_event  # type: ignore[method-assign]

        p = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=logger,
            config=config,
            tool_registry=registry,
        )
        # Simulate two tool calls
        await p.on_tool_called("s1", "unknown_a", {})
        await p.on_tool_called("s1", "unknown_b", {})
        await p.get_tools_for_list("s1")
        assert len(logged_events) == 1
        assert logged_events[0].turn_number == 2


class TestDynamicK:
    """Dynamic K computation: base 15, +3 if polyglot, cap at 20."""

    @pytest.mark.asyncio
    async def test_default_max_k_20_stays_20(self):
        """max_k=20 (default): base_k=max(15,20)=20, polyglot_bonus=0, result=20."""
        config = RetrievalConfig(enabled=True, max_k=20)
        # Create 25 tools to test cap
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(25)
        }
        p = _make_pipeline(registry=registry, config=config)
        p.session_manager.get_or_create_session("s1")
        # Seed all 25 tools into session
        p.session_manager.add_tools("s1", list(registry.keys()))
        tools = await p.get_tools_for_list("s1")
        # Dynamic K: max_k=20 -> no polyglot bonus -> stays at 20
        assert len(tools) <= 20

    @pytest.mark.asyncio
    async def test_max_k_10_bumped_to_base_15(self):
        """max_k=10: base_k=max(15,10)=15, polyglot_bonus=0, result=15."""
        config = RetrievalConfig(enabled=True, max_k=10)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(20)
        }
        p = _make_pipeline(registry=registry, config=config)
        p.session_manager.get_or_create_session("s1")
        p.session_manager.add_tools("s1", list(registry.keys()))
        tools = await p.get_tools_for_list("s1")
        # base_k = max(15, 10) = 15; no polyglot bonus
        assert len(tools) <= 15
        assert len(tools) >= 15  # should exactly be 15 (20 tools available, K=15)

    @pytest.mark.asyncio
    async def test_max_k_18_adds_polyglot_bonus(self):
        """max_k=18 (>17): base_k=max(15,18)=18, polyglot_bonus=3, min(20,21)=20."""
        config = RetrievalConfig(enabled=True, max_k=18)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(25)
        }
        p = _make_pipeline(registry=registry, config=config)
        p.session_manager.get_or_create_session("s1")
        p.session_manager.add_tools("s1", list(registry.keys()))
        tools = await p.get_tools_for_list("s1")
        # base_k=18, polyglot_bonus=3 -> 21, cap at 20
        assert len(tools) <= 20

    @pytest.mark.asyncio
    async def test_max_k_less_than_15_uses_15(self):
        """max_k=5: base_k=max(15,5)=15, no polyglot. Never expose fewer than 15."""
        config = RetrievalConfig(enabled=True, max_k=5)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(20)
        }
        p = _make_pipeline(registry=registry, config=config)
        p.session_manager.get_or_create_session("s1")
        p.session_manager.add_tools("s1", list(registry.keys()))
        tools = await p.get_tools_for_list("s1")
        # base_k = max(15, 5) = 15
        assert len(tools) == 15


class TestFusionImport:
    """pipeline.py imports fusion module (try/except pattern)."""

    def test_has_fusion_flag(self):
        """pipeline module should have _HAS_FUSION attribute."""
        import src.multimcp.retrieval.pipeline as pipeline_mod
        assert hasattr(pipeline_mod, "_HAS_FUSION")

    def test_fusion_available(self):
        """Since fusion.py exists, _HAS_FUSION should be True."""
        import src.multimcp.retrieval.pipeline as pipeline_mod
        assert pipeline_mod._HAS_FUSION is True
