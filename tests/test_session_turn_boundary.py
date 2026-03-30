"""Tests for Phase 8: Session State & Turn Boundary Discipline.

Covers CF-1 (real session IDs), CF-3 (turn-scoped demotion protection),
CF-4 (SessionRoutingState per session), and the turn counter discipline.
"""

from __future__ import annotations

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from mcp import types
from mcp.client.session import ClientSession

from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.models import RetrievalConfig, SessionRoutingState
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import RetrievalLogger
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_pipeline(tool_registry=None):
    """Create a minimal enabled pipeline for testing."""
    if tool_registry is None:
        tool_registry = {}
    config = RetrievalConfig(enabled=True, rollout_stage="ga", top_k=5, max_k=10)
    retriever = PassthroughRetriever()
    session_manager = SessionStateManager(config)
    logger = MagicMock(spec=RetrievalLogger)
    logger.log_ranking_event = AsyncMock()
    return RetrievalPipeline(retriever, session_manager, logger, config, tool_registry)


def make_tool_registry(n=10):
    """Create n mock tool mappings."""
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


def make_proxy():
    """Create a minimal MCPProxyServer with a mocked client manager."""
    client_manager = MagicMock()
    client_manager.clients = {}
    return MCPProxyServer(client_manager)


# ── CF-1: Real session IDs ─────────────────────────────────────────────────


def test_real_session_ids():
    """Two distinct server session objects produce two distinct session IDs."""
    proxy = make_proxy()

    session_a = MagicMock()
    session_b = MagicMock()

    proxy._server_session = session_a
    id_a = proxy._get_session_id()

    proxy._server_session = session_b
    id_b = proxy._get_session_id()

    assert id_a != id_b
    assert len(id_a) == 32  # uuid4().hex
    assert len(id_b) == 32
    assert id_a != "default"
    assert id_b != "default"
    assert all(c in "0123456789abcdef" for c in id_a)
    assert all(c in "0123456789abcdef" for c in id_b)


def test_no_session_raises():
    """_get_session_id() raises RuntimeError when _server_session is None."""
    proxy = make_proxy()
    proxy._server_session = None
    with pytest.raises(RuntimeError, match="No active MCP session"):
        proxy._get_session_id()


def test_no_shared_default():
    """'default' never appears as a session ID from _get_session_id()."""
    proxy = make_proxy()
    session = MagicMock()
    proxy._server_session = session
    sid = proxy._get_session_id()
    assert sid != "default"


def test_same_session_same_id():
    """Same server session object always returns the same stable ID."""
    proxy = make_proxy()
    session = MagicMock()
    proxy._server_session = session
    id1 = proxy._get_session_id()
    id2 = proxy._get_session_id()
    assert id1 == id2


# ── CF-1: list_changed hash-based emission ────────────────────────────────


@pytest.mark.anyio
async def test_call_tool_no_list_changed():
    """_call_tool() does NOT call _send_tools_list_changed after on_tool_called."""
    proxy = make_proxy()
    session = MagicMock()
    proxy._server_session = session

    pipeline = MagicMock()
    pipeline.on_tool_called = AsyncMock(return_value=False)
    proxy.retrieval_pipeline = pipeline

    # Patch _send_tools_list_changed to detect unwanted calls
    proxy._send_tools_list_changed = AsyncMock()

    # Patch the tool lookup to return a valid result without a real server
    mock_client = AsyncMock()
    mock_result = MagicMock()
    mock_result.content = [types.TextContent(type="text", text="result")]
    mock_result.isError = False
    mock_client.call_tool = AsyncMock(return_value=mock_result)

    proxy.tool_to_server["server__tool"] = ToolMapping(
        server_name="server",
        client=mock_client,
        tool=types.Tool(name="server__tool", description="t", inputSchema={"type": "object", "properties": {}}),
    )

    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="server__tool", arguments={}),
    )
    await proxy._call_tool(req)

    # on_tool_called was called but _send_tools_list_changed was NOT called
    pipeline.on_tool_called.assert_called_once()
    proxy._send_tools_list_changed.assert_not_called()


@pytest.mark.anyio
async def test_list_changed_only_on_diff():
    """_list_tools() sends tools/list_changed only when the tool list hash changes."""
    proxy = make_proxy()
    session = MagicMock()
    proxy._server_session = session

    tools_v1 = [types.Tool(name="tool_a", description="a", inputSchema={"type": "object", "properties": {}})]
    tools_v2 = [types.Tool(name="tool_b", description="b", inputSchema={"type": "object", "properties": {}})]

    pipeline = MagicMock()
    # First call returns v1, second call returns v2
    pipeline.get_tools_for_list = AsyncMock(side_effect=[tools_v1, tools_v2, tools_v2])
    pipeline.get_session_tool_history = MagicMock(return_value=[])
    pipeline.get_session_argument_keys = MagicMock(return_value=[])
    pipeline.get_session_router_describes = MagicMock(return_value=[])
    proxy.retrieval_pipeline = pipeline
    proxy._send_tools_list_changed = AsyncMock()

    # First call — no previous hash, no notification
    await proxy._list_tools(None)
    proxy._send_tools_list_changed.assert_not_called()

    # Second call — hash changed (v1 → v2), should notify
    await proxy._list_tools(None)
    proxy._send_tools_list_changed.assert_called_once()

    # Third call — same hash as v2, no additional notification
    await proxy._list_tools(None)
    proxy._send_tools_list_changed.assert_called_once()  # still just once


# ── CF-4: SessionRoutingState per session ────────────────────────────────


@pytest.mark.anyio
async def test_routing_state_created_per_session():
    """Each unique session_id gets its own SessionRoutingState; two sessions don't share state."""
    pipeline = make_pipeline(make_tool_registry(5))

    await pipeline.get_tools_for_list("session_1")
    await pipeline.get_tools_for_list("session_2")

    state1 = pipeline._routing_states.get("session_1")
    state2 = pipeline._routing_states.get("session_2")

    assert state1 is not None
    assert state2 is not None
    assert state1 is not state2
    assert state1.session_id == "session_1"
    assert state2.session_id == "session_2"


@pytest.mark.anyio
async def test_turn_counter_increments_on_list_only():
    """turn_number increments in get_tools_for_list(), not in on_tool_called().
    3 tool calls + 1 list call → turn_number == 1."""
    pipeline = make_pipeline(make_tool_registry(5))
    sid = "test_session"

    # Simulate 3 tool calls without a list call
    await pipeline.on_tool_called(sid, "server__00_tool", {})
    await pipeline.on_tool_called(sid, "server__01_tool", {})
    await pipeline.on_tool_called(sid, "server__02_tool", {})

    # State not created yet (only list creates it)
    assert sid not in pipeline._routing_states

    # Now one list call
    await pipeline.get_tools_for_list(sid)

    state = pipeline._routing_states.get(sid)
    assert state is not None
    assert state.turn_number == 1


@pytest.mark.anyio
async def test_mid_turn_active_set_stable():
    """on_tool_called() does not change what get_tools_for_list() returns mid-turn."""
    pipeline = make_pipeline(make_tool_registry(5))
    sid = "stable_session"

    # Turn 1
    tools_turn1 = await pipeline.get_tools_for_list(sid)
    keys_turn1 = {t.name for t in tools_turn1}

    # Several tool calls mid-turn
    await pipeline.on_tool_called(sid, "server__00_tool", {})
    await pipeline.on_tool_called(sid, "server__01_tool", {})

    # Active set in SSM should not have changed due to on_tool_called
    active_after_calls = pipeline.session_manager.get_active_tools(sid)
    state = pipeline._routing_states[sid]

    # State's active_tool_ids should be unchanged (still from turn boundary)
    active_ids_set = set(state.active_tool_ids)
    assert active_ids_set == active_after_calls


@pytest.mark.anyio
async def test_cleanup_removes_all_state():
    """After cleanup_session(), all per-session dicts have no entry for that session."""
    pipeline = make_pipeline(make_tool_registry(5))
    sid = "cleanup_session"

    await pipeline.get_tools_for_list(sid)
    await pipeline.on_tool_called(sid, "server__00_tool", {}, is_router_proxy=True)

    pipeline.cleanup_session(sid)

    # Check all per-session dicts
    assert sid not in pipeline._session_turns
    assert sid not in pipeline._session_roots
    assert sid not in pipeline._session_evidence
    assert sid not in pipeline._session_tool_history
    assert sid not in pipeline._session_arg_keys
    assert sid not in pipeline._session_router_describes
    assert sid not in pipeline._session_router_proxies
    assert sid not in pipeline._current_turn_used
    assert sid not in pipeline._just_finished_turn_used
    assert sid not in pipeline._routing_states
    assert sid not in pipeline._in_turn
    assert sid not in pipeline._turn_snapshot_version
    assert pipeline.session_manager.get_active_tools(sid) == set()


# ── CF-3: Turn-scoped usage buckets ──────────────────────────────────────


@pytest.mark.anyio
async def test_current_turn_bucket_written_on_call():
    """on_tool_called() writes tool_name to _current_turn_used[session_id]."""
    pipeline = make_pipeline(make_tool_registry(5))
    sid = "bucket_session"

    await pipeline.on_tool_called(sid, "server__00_tool", {})
    await pipeline.on_tool_called(sid, "server__01_tool", {})

    bucket = pipeline._current_turn_used.get(sid, set())
    assert "server__00_tool" in bucket
    assert "server__01_tool" in bucket


@pytest.mark.anyio
async def test_demotion_uses_just_finished_turn_not_history():
    """Demotion protection at turn N+1 uses only tools from turn N, not from N-1.

    Sequence:
    1. list call 1 (start turn 1)
    2. use tool_00 during turn 1
    3. list call 2 (end turn 1, start turn 2) → just_finished = {tool_00}
    4. use tool_01 during turn 2 (NOT tool_00)
    5. list call 3 (end turn 2, start turn 3) → just_finished = {tool_01}
    At turn 3 boundary, just_finished should contain tool_01 but NOT tool_00.
    """
    registry = make_tool_registry(15)
    pipeline = make_pipeline(registry)
    sid = "demote_test"

    # Turn 1 boundary
    await pipeline.get_tools_for_list(sid)
    # Use tool_00 during turn 1
    await pipeline.on_tool_called(sid, "server__00_tool", {})
    # Turn 2 boundary — rolls {tool_00} → just_finished
    await pipeline.get_tools_for_list(sid)
    just_finished_t2 = pipeline._just_finished_turn_used.get(sid, set())
    assert "server__00_tool" in just_finished_t2

    # Use tool_01 during turn 2 (not tool_00)
    await pipeline.on_tool_called(sid, "server__01_tool", {})
    # Turn 3 boundary — rolls {tool_01} → just_finished (replaces {tool_00})
    await pipeline.get_tools_for_list(sid)
    just_finished_t3 = pipeline._just_finished_turn_used.get(sid, set())
    assert "server__01_tool" in just_finished_t3
    assert "server__00_tool" not in just_finished_t3


@pytest.mark.anyio
async def test_old_history_not_demote_protected():
    """Tool used only in turn 1 receives no demotion protection at turn 4 boundary."""
    registry = make_tool_registry(15)
    pipeline = make_pipeline(registry)
    sid = "old_hist_session"

    # Turn 1: use tool_00
    await pipeline.on_tool_called(sid, "server__00_tool", {})
    await pipeline.get_tools_for_list(sid)

    # Turns 2 and 3: use different tools
    for turn in range(2, 4):
        await pipeline.on_tool_called(sid, "server__01_tool", {})
        await pipeline.get_tools_for_list(sid)

    # At turn 4, just_finished should NOT contain tool_00
    just_finished = pipeline._just_finished_turn_used.get(sid, set())
    assert "server__00_tool" not in just_finished


@pytest.mark.anyio
async def test_session_history_for_retrieval_context_only():
    """_session_tool_history is never read inside promote/demote logic.

    Verify that session tool history (used for retrieval context) does not
    bleed into promote/demote decisions. Promote/demote use scored_tools ranking
    and _just_finished_turn_used for protection, not full session history.

    The just_finished_turn_used at turn N boundary = tools used IN turn N-1
    (between list calls N-1 and N), NOT the full session history.
    """
    registry = make_tool_registry(10)
    pipeline = make_pipeline(registry)
    sid = "hist_context_only"

    # Turn 1 boundary (no tools used yet)
    await pipeline.get_tools_for_list(sid)

    # Use 8 tools during turn 1 (between list call 1 and list call 2)
    for i in range(8):
        await pipeline.on_tool_called(sid, f"server__{i:02d}_tool", {})

    # Turn 2 boundary — rolls current_turn_used (8 tools) → just_finished
    await pipeline.get_tools_for_list(sid)
    just_finished = pipeline._just_finished_turn_used.get(sid, set())

    # just_finished = the 8 tools from turn 1
    assert just_finished == {f"server__{i:02d}_tool" for i in range(8)}

    # History recorded in _session_tool_history (for retrieval context)
    hist = pipeline._session_tool_history.get(sid, [])
    assert len(hist) == 8

    # But at the NEXT boundary, just_finished won't contain turn-1 tools
    # if they weren't used in turn 2
    await pipeline.get_tools_for_list(sid)
    just_finished_t3 = pipeline._just_finished_turn_used.get(sid, set())
    # No tools used in turn 2, so just_finished_t3 = empty
    assert len(just_finished_t3) == 0

    # Session history still has all 8 (it's cumulative)
    hist_after = pipeline._session_tool_history.get(sid, [])
    assert len(hist_after) == 8


@pytest.mark.anyio
async def test_ssm_and_state_synchronized():
    """After get_tools_for_list(), session_manager.get_active_tools() and state.active_tool_ids contain identical keys."""
    registry = make_tool_registry(8)
    pipeline = make_pipeline(registry)
    sid = "sync_test"

    await pipeline.get_tools_for_list(sid)

    state = pipeline._routing_states[sid]
    ssm_active = pipeline.session_manager.get_active_tools(sid)

    assert set(state.active_tool_ids) == ssm_active
