"""Tests for Phase 8: Snapshot Pinning & Rebuild Deferral (CF-4).

Covers catalog_version pinning per turn, mid-turn rebuild deferral,
and pending rebuild application at next boundary.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from mcp import types
from mcp.client.session import ClientSession

from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.logging import RetrievalLogger
from src.multimcp.mcp_proxy import ToolMapping


# ── Mock retriever with snapshot version support ─────────────────────────────


class MockRetrieverWithVersion:
    """Retriever stub that exposes a configurable snapshot version."""

    def __init__(self, version: str = "v1") -> None:
        self._version = version
        self._rebuilt_registry: dict | None = None

    def get_snapshot_version(self) -> str:
        return self._version

    async def retrieve(self, ctx, candidates):
        return []

    def rebuild_index(self, registry: dict) -> None:
        self._rebuilt_registry = registry


def make_tool_registry(n: int = 5) -> dict:
    reg = {}
    for i in range(n):
        key = f"server__{i:02d}_tool"
        tool = types.Tool(
            name=f"{i:02d}_tool",
            description=f"Tool {i}",
            inputSchema={"type": "object", "properties": {}},
        )
        reg[key] = ToolMapping(server_name="server", client=None, tool=tool)
    return reg


def make_pipeline_with_retriever(retriever, tool_registry=None):
    if tool_registry is None:
        tool_registry = make_tool_registry(5)
    config = RetrievalConfig(enabled=True, rollout_stage="ga", top_k=5, max_k=10)
    session_manager = SessionStateManager(config)
    logger = MagicMock(spec=RetrievalLogger)
    logger.log_ranking_event = AsyncMock()
    return RetrievalPipeline(retriever, session_manager, logger, config, tool_registry)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_turn_pinned_to_snapshot():
    """RankingEvent.catalog_version equals snapshot version at turn start."""
    retriever = MockRetrieverWithVersion(version="abc123")
    pipeline = make_pipeline_with_retriever(retriever)
    sid = "snap_session"

    await pipeline.get_tools_for_list(sid)

    event = pipeline.logger.log_ranking_event.call_args[0][0]
    assert event.catalog_version == "abc123"


@pytest.mark.anyio
async def test_rebuild_deferred_mid_turn():
    """rebuild_catalog() called while _in_turn[session_id] is True defers rebuild."""
    retriever = MockRetrieverWithVersion(version="v1")
    pipeline = make_pipeline_with_retriever(retriever)
    sid = "defer_session"

    # Initiate a turn so _in_turn becomes True
    await pipeline.get_tools_for_list(sid)
    assert pipeline._in_turn.get(sid) is True

    # Now call rebuild_catalog while mid-turn
    new_registry = make_tool_registry(8)
    pipeline.rebuild_catalog(new_registry)

    # Should have deferred — pending_rebuild is set, retriever was NOT rebuilt yet
    assert pipeline._pending_rebuild is not None
    assert retriever._rebuilt_registry is None


@pytest.mark.anyio
async def test_pending_rebuild_applies_next_boundary():
    """Deferred rebuild executes at next get_tools_for_list() when no session is mid-turn."""
    retriever = MockRetrieverWithVersion(version="v1")
    pipeline = make_pipeline_with_retriever(retriever)
    sid = "rebuild_apply_session"

    # Turn 1 — sets _in_turn = True
    await pipeline.get_tools_for_list(sid)

    new_registry = make_tool_registry(8)
    pipeline.rebuild_catalog(new_registry)
    assert pipeline._pending_rebuild is not None

    # Turn 2 — at boundary, _in_turn becomes False (close previous turn),
    # then pending rebuild should execute before scoring
    await pipeline.get_tools_for_list(sid)

    assert pipeline._pending_rebuild is None
    assert retriever._rebuilt_registry is not None
    assert len(retriever._rebuilt_registry) == 8


@pytest.mark.anyio
async def test_ranking_event_catalog_version():
    """catalog_version is never empty string when pipeline is enabled with a versioned retriever."""
    retriever = MockRetrieverWithVersion(version="v_xyz_42")
    pipeline = make_pipeline_with_retriever(retriever)
    sid = "cv_session"

    await pipeline.get_tools_for_list(sid)

    event = pipeline.logger.log_ranking_event.call_args[0][0]
    assert event.catalog_version != ""
    assert event.catalog_version == "v_xyz_42"


@pytest.mark.anyio
async def test_catalog_version_stable_within_turn():
    """catalog_version in state is pinned at turn start even if retriever version changes."""
    retriever = MockRetrieverWithVersion(version="v1")
    pipeline = make_pipeline_with_retriever(retriever)
    sid = "cv_stable_session"

    await pipeline.get_tools_for_list(sid)
    state = pipeline._routing_states[sid]
    assert state.catalog_version == "v1"

    # Simulate a retriever version update mid-turn
    retriever._version = "v2"

    # The state.catalog_version should still reflect the pinned version from turn start
    # (it was set at boundary and won't update until next list call)
    assert state.catalog_version == "v1"

    # Next turn boundary
    await pipeline.get_tools_for_list(sid)
    assert state.catalog_version == "v2"
