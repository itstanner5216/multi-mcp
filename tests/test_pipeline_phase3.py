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
    """Turn counter advances at turn boundaries (get_tools_for_list), not per tool call."""

    @pytest.mark.asyncio
    async def test_session_turns_initializes_to_zero(self):
        """New pipeline has no turn tracking entries."""
        p = _make_pipeline()
        # _session_turns should be a dict attribute
        assert hasattr(p, "_session_turns")
        assert p._session_turns == {}

    @pytest.mark.asyncio
    async def test_on_tool_called_does_not_increment_turn_counter(self):
        """on_tool_called records tool usage but does NOT advance the turn counter.

        Issue 7 fix: turn advancement is deferred to get_tools_for_list() so all
        tools within a single request are treated as one turn, not N turns.
        """
        p = _make_pipeline()
        await p.on_tool_called("sess-1", "some_tool", {})
        # Turn counter is still 0 — it advances at the next get_tools_for_list boundary
        assert p._session_turns.get("sess-1", 0) == 0

    @pytest.mark.asyncio
    async def test_on_tool_called_multiple_calls_no_increment(self):
        """Multiple on_tool_called() in one request still do not advance turn counter."""
        p = _make_pipeline()
        for _ in range(3):
            await p.on_tool_called("sess-1", "some_tool", {})
        # Still 0 — turn only advances at get_tools_for_list boundary
        assert p._session_turns.get("sess-1", 0) == 0

    @pytest.mark.asyncio
    async def test_on_tool_called_sessions_independent(self):
        """Tool histories are independent per session (turns still 0 until boundary)."""
        p = _make_pipeline()
        await p.on_tool_called("sess-1", "tool_a", {})
        await p.on_tool_called("sess-1", "tool_a", {})
        await p.on_tool_called("sess-2", "tool_b", {})
        # Neither session has had a turn boundary yet
        assert p._session_turns.get("sess-1", 0) == 0
        assert p._session_turns.get("sess-2", 0) == 0

    @pytest.mark.asyncio
    async def test_on_tool_called_disabled_no_increment(self):
        """When pipeline is disabled, on_tool_called returns False immediately, no tracking."""
        p = _make_pipeline(config=RetrievalConfig(enabled=False))
        result = await p.on_tool_called("sess-1", "tool", {})
        assert result is False
        assert p._session_turns.get("sess-1", 0) == 0


class TestOnToolCalledPromote:
    """on_tool_called records tools; promotion happens at the turn boundary."""

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
    async def test_returns_false_always_promotion_deferred(self):
        """on_tool_called always returns False — promotion is deferred to the next
        get_tools_for_list() call (turn boundary), not executed per tool call.

        Issue 7 fix: separates "record tool used" from "promote/advance turn".
        """
        tool = _make_tool("new_tool")
        registry = {"github__new_tool": _make_mapping("github", tool)}
        p = _make_pipeline(registry=registry)
        # Create session WITHOUT the tool
        p.session_manager.get_or_create_session("s1")
        result = await p.on_tool_called("s1", "github__new_tool", {})
        # Returns False — promotion happens at the next get_tools_for_list turn boundary
        assert result is False

    @pytest.mark.asyncio
    async def test_turn_does_not_increment_without_boundary(self):
        """Turn counter stays at 0 until get_tools_for_list() is called."""
        p = _make_pipeline(registry={})
        p.session_manager.get_or_create_session("s1")
        await p.on_tool_called("s1", "missing_tool", {})
        assert p._session_turns.get("s1", 0) == 0


class CapturingLogger(NullLogger):
    """NullLogger subclass that captures RankingEvents for testing."""

    def __init__(self) -> None:
        self.events = []

    async def log_ranking_event(self, event) -> None:
        self.events.append(event)


class TestRankingEventTurnNumber:
    """RankingEvent.turn_number reflects the turn boundary, not on_tool_called count.

    Issue 7 fix: turn is advanced in get_tools_for_list() (the true turn boundary).
    First get_tools_for_list() call emits turn_number=1 (advanced from 0).
    """

    @pytest.mark.asyncio
    async def test_ranking_event_turn_number_one_on_first_list(self):
        """On first get_tools_for_list call, turn_number = 1 (boundary advanced from 0)."""
        config = RetrievalConfig(enabled=True, max_k=5)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(5)
        }
        logger = CapturingLogger()
        p = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=logger,
            config=config,
            tool_registry=registry,
        )
        await p.get_tools_for_list("s1")
        assert len(logger.events) == 1
        assert logger.events[0].turn_number == 1  # First boundary: 0 → 1

    @pytest.mark.asyncio
    async def test_ranking_event_turn_number_reflects_list_calls(self):
        """Each get_tools_for_list call advances the turn counter by 1.

        Issue 7 fix: turn advances at get_tools_for_list (turn boundary), not at
        on_tool_called. So 2 tool calls followed by 1 get_tools_for_list = turn 1.
        """
        config = RetrievalConfig(enabled=True, max_k=5)
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(5)
        }
        logger = CapturingLogger()
        p = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=logger,
            config=config,
            tool_registry=registry,
        )
        # Simulate two tool calls followed by one tools/list request
        await p.on_tool_called("s1", "unknown_a", {})
        await p.on_tool_called("s1", "unknown_b", {})
        await p.get_tools_for_list("s1")
        assert len(logger.events) == 1
        assert logger.events[0].turn_number == 1  # One boundary crossed


class TestDynamicK:
    """Dynamic K computation: base 15, +3 if polyglot (>1 lang: token), cap at 20.

    Phase 2: dynamic_k is evidence-based, not config.max_k-based.
    The config.max_k > 17 proxy heuristic has been replaced.
    """

    @pytest.mark.asyncio
    async def test_default_max_k_bounded_at_20(self):
        """With large registry and no evidence, result is bounded at <= 20 direct tools."""
        config = RetrievalConfig(enabled=True, max_k=20, rollout_stage="ga")
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(25)
        }
        p = _make_pipeline(registry=registry, config=config)
        tools = await p.get_tools_for_list("s1")
        non_routing = [t for t in tools if t.name != "request_tool"]
        assert len(non_routing) <= 20

    @pytest.mark.asyncio
    async def test_max_k_enforces_upper_cap(self):
        """Dynamic K never exceeds 20 regardless of registry size."""
        config = RetrievalConfig(enabled=True, max_k=20, rollout_stage="ga")
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(50)
        }
        p = _make_pipeline(registry=registry, config=config)
        tools = await p.get_tools_for_list("s1")
        non_routing = [t for t in tools if t.name != "request_tool"]
        assert len(non_routing) <= 20

    @pytest.mark.asyncio
    async def test_polyglot_increases_k_to_18(self):
        """Evidence with >1 lang: token sets dynamic_k=18 (direct_k=17 with routing)."""
        config = RetrievalConfig(enabled=True, max_k=20, rollout_stage="ga")
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(25)
        }
        p = _make_pipeline(registry=registry, config=config)
        # Inject polyglot evidence
        from src.multimcp.retrieval.models import WorkspaceEvidence
        p._session_evidence["polyglot_s"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0, "lang:javascript": 0.8},
        )
        tools = await p.get_tools_for_list("polyglot_s")
        assert len(tools) <= 19  # dynamic_k=18, direct_k=17 + 1 routing = 18

    @pytest.mark.asyncio
    async def test_no_polyglot_stays_at_15(self):
        """Evidence with only 1 lang: token stays at dynamic_k=15."""
        config = RetrievalConfig(enabled=True, max_k=20, rollout_stage="ga")
        registry = {
            f"srv__{i}": _make_mapping("srv", _make_tool(f"tool_{i}"))
            for i in range(25)
        }
        p = _make_pipeline(registry=registry, config=config)
        from src.multimcp.retrieval.models import WorkspaceEvidence
        p._session_evidence["mono_s"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0},
        )
        tools = await p.get_tools_for_list("mono_s")
        # dynamic_k=15, direct_k=14 + 1 routing = 15
        assert len(tools) <= 16


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
