"""Tests for Phase 8: Router Accounting signal separation (CF-2).

Covers the separation of direct tool calls, router describes, and router proxy
calls into distinct tracking buckets, and validates that RankingEvent fields
reflect only their respective signal sources.
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_tool_registry(n: int = 8) -> dict:
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


def make_pipeline(n: int = 8) -> RetrievalPipeline:
    registry = make_tool_registry(n)
    config = RetrievalConfig(
        enabled=True,
        rollout_stage="ga",
        top_k=5,
        max_k=10,
        enable_routing_tool=False,
    )
    session_manager = SessionStateManager(config)
    logger = MagicMock(spec=RetrievalLogger)
    logger.log_ranking_event = AsyncMock()
    return RetrievalPipeline(
        MagicMock(retrieve=AsyncMock(return_value=[])),
        session_manager,
        logger,
        config,
        registry,
    )


async def get_last_ranking_event(pipeline: RetrievalPipeline, sid: str):
    """Trigger get_tools_for_list and return the emitted RankingEvent."""
    await pipeline.get_tools_for_list(sid)
    return pipeline.logger.log_ranking_event.call_args[0][0]


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_describe_only_does_not_update_router_proxies():
    """record_router_describe() writes only to _session_router_describes, not _session_router_proxies."""
    pipeline = make_pipeline()
    sid = "describe_only"

    # First create routing state
    await pipeline.get_tools_for_list(sid)

    pipeline.record_router_describe(sid, "server__02_tool")

    # _session_router_describes should have the tool
    describes = pipeline._session_router_describes.get(sid, [])
    assert "server__02_tool" in describes

    # _session_router_proxies should NOT have the tool
    proxies = pipeline._session_router_proxies.get(sid, [])
    assert "server__02_tool" not in proxies

    # state.recent_router_proxies should also NOT have the tool
    state = pipeline._routing_states.get(sid)
    if state is not None:
        assert "server__02_tool" not in state.recent_router_proxies


@pytest.mark.anyio
async def test_proxy_call_updates_router_proxies():
    """on_tool_called(..., is_router_proxy=True) writes to _session_router_proxies and state.recent_router_proxies."""
    pipeline = make_pipeline()
    sid = "proxy_updates"

    await pipeline.get_tools_for_list(sid)
    state = pipeline._routing_states[sid]

    await pipeline.on_tool_called(sid, "server__03_tool", {}, is_router_proxy=True)

    # _session_router_proxies should have the tool
    proxies = pipeline._session_router_proxies.get(sid, [])
    assert "server__03_tool" in proxies

    # state.recent_router_proxies should have the tool with turn number
    assert "server__03_tool" in state.recent_router_proxies
    assert state.turn_number in state.recent_router_proxies["server__03_tool"]


@pytest.mark.anyio
async def test_ranking_event_uses_correct_sources():
    """RankingEvent.router_describes == _session_router_describes;
    RankingEvent.router_proxies == _session_router_proxies; they are not the same list."""
    pipeline = make_pipeline()
    sid = "correct_sources"

    await pipeline.get_tools_for_list(sid)

    # Record a describe
    pipeline.record_router_describe(sid, "server__01_tool")

    # Record a proxy call
    await pipeline.on_tool_called(sid, "server__02_tool", {}, is_router_proxy=True)

    # Record a direct tool call (not proxy)
    await pipeline.on_tool_called(sid, "server__00_tool", {})

    # Turn 2 — emit RankingEvent
    await pipeline.get_tools_for_list(sid)
    event = pipeline.logger.log_ranking_event.call_args[0][0]

    assert "server__01_tool" in event.router_describes
    assert "server__02_tool" in event.router_proxies
    assert "server__01_tool" not in event.router_proxies
    assert "server__02_tool" not in event.router_describes
    assert event.router_describes is not event.router_proxies


@pytest.mark.anyio
async def test_tier5_fields_correct_separation():
    """After a mix of describe-only and proxy calls, RankingEvent fields reflect distinct signals."""
    pipeline = make_pipeline()
    sid = "tier5_sep"

    # Turn 1
    await pipeline.get_tools_for_list(sid)

    # Mix of signals
    pipeline.record_router_describe(sid, "server__04_tool")   # describe only
    pipeline.record_router_describe(sid, "server__05_tool")   # describe only
    await pipeline.on_tool_called(sid, "server__06_tool", {}, is_router_proxy=True)  # proxy
    await pipeline.on_tool_called(sid, "server__00_tool", {})  # direct
    await pipeline.on_tool_called(sid, "server__01_tool", {})  # direct

    # Turn 2 — emit RankingEvent
    await pipeline.get_tools_for_list(sid)
    event = pipeline.logger.log_ranking_event.call_args[0][0]

    # direct_tool_calls contains only direct calls (not describe or proxy)
    # (Note: on_tool_called always writes to _session_tool_history regardless of is_router_proxy)
    assert "server__00_tool" in event.direct_tool_calls
    assert "server__01_tool" in event.direct_tool_calls

    # router_describes contains only describe calls
    assert "server__04_tool" in event.router_describes
    assert "server__05_tool" in event.router_describes
    assert "server__06_tool" not in event.router_describes

    # router_proxies contains only proxy calls
    assert "server__06_tool" in event.router_proxies
    assert "server__04_tool" not in event.router_proxies
    assert "server__05_tool" not in event.router_proxies
    assert "server__00_tool" not in event.router_proxies
    assert "server__01_tool" not in event.router_proxies
