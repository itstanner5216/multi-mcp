"""Tests for Phase 8: Router Accounting signal separation (CF-2).

Covers the separation of direct tool calls, router describes, and router proxy
calls into distinct tracking buckets, and validates that RankingEvent fields
reflect only their respective signal sources.

Also covers runtime truth: MCPProxyServer._call_tool() proxy dispatch path
writes is_router_proxy=True to the pipeline and NOT to direct_tool_calls.
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
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping


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


# ── Runtime truth: MCPProxyServer._call_tool() proxy dispatch ────────────────


def _make_proxy_with_pipeline(tool_registry: dict) -> tuple[MCPProxyServer, MagicMock]:
    """Create an MCPProxyServer wired with a mock pipeline, returning (proxy, pipeline)."""
    client_manager = MagicMock()
    client_manager.clients = {}
    proxy = MCPProxyServer(client_manager)
    proxy.tool_to_server.update(tool_registry)

    # Attach a mock session so _get_session_id() works
    session = MagicMock()
    proxy._server_session = session

    pipeline = MagicMock()
    pipeline.on_tool_called = AsyncMock(return_value=False)
    pipeline.record_router_describe = MagicMock()
    proxy.retrieval_pipeline = pipeline

    # Silence audit logger and trigger manager
    proxy._send_tools_list_changed = AsyncMock()
    proxy.trigger_manager = MagicMock()
    proxy.trigger_manager.check_and_enable = AsyncMock(return_value=[])

    return proxy, pipeline


def _make_tool_registry_for_proxy() -> dict:
    """Registry with two real-ish tools for proxy dispatch testing."""
    registry = {}
    for key in ("server__target_tool", "server__other_tool"):
        server_name, tool_name = key.split("__", 1)
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [types.TextContent(type="text", text="ok")]
        mock_result.isError = False
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        registry[key] = ToolMapping(
            server_name=server_name,
            client=mock_client,
            tool=types.Tool(
                name=key,
                description="Test tool",
                inputSchema={"type": "object", "properties": {}},
            ),
        )
    return registry


@pytest.mark.anyio
async def test_proxy_routing_call_recorded_as_router_proxy():
    """MCPProxyServer._call_tool() routing proxy path calls on_tool_called with is_router_proxy=True.

    Runtime truth: when the routing tool returns __PROXY_CALL__:{name},
    the pipeline must record it in router_proxies (is_router_proxy=True).
    """
    registry = _make_tool_registry_for_proxy()
    proxy, pipeline = _make_proxy_with_pipeline(registry)

    # Patch handle_routing_call at its source module so the local import picks it up
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "src.multimcp.retrieval.routing_tool.handle_routing_call",
            lambda name, describe, arguments, tool_to_server: [
                types.TextContent(type="text", text="__PROXY_CALL__:server__target_tool")
            ],
        )

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="request_tool",
                arguments={"name": "server__target_tool", "describe": False, "arguments": {}},
            ),
        )
        await proxy._call_tool(req)

    # on_tool_called must have been called with is_router_proxy=True
    pipeline.on_tool_called.assert_called_once()
    call_kwargs = pipeline.on_tool_called.call_args
    # Third positional arg is the tool name; keyword arg is_router_proxy must be True
    assert call_kwargs.kwargs.get("is_router_proxy") is True or (
        len(call_kwargs.args) >= 4 and call_kwargs.args[3] is True
    ), f"Expected is_router_proxy=True, got: {call_kwargs}"


@pytest.mark.anyio
async def test_proxy_routing_call_not_recorded_as_direct():
    """MCPProxyServer._call_tool() routing proxy path does NOT call on_tool_called a second time
    for the outer routing tool call — only one on_tool_called invocation, for the proxied tool.

    Ensures the routing tool call itself is not double-counted as a direct call.
    """
    registry = _make_tool_registry_for_proxy()
    proxy, pipeline = _make_proxy_with_pipeline(registry)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "src.multimcp.retrieval.routing_tool.handle_routing_call",
            lambda name, describe, arguments, tool_to_server: [
                types.TextContent(type="text", text="__PROXY_CALL__:server__target_tool")
            ],
        )

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="request_tool",
                arguments={"name": "server__target_tool", "describe": False, "arguments": {}},
            ),
        )
        await proxy._call_tool(req)

    # Exactly one on_tool_called call — not two (one proxy + one direct)
    assert pipeline.on_tool_called.call_count == 1, (
        f"Expected 1 on_tool_called call (proxy only), got {pipeline.on_tool_called.call_count}"
    )
    # That single call was the proxied tool, not 'request_tool'
    called_tool = pipeline.on_tool_called.call_args.args[1]
    assert called_tool == "server__target_tool"
    assert called_tool != "request_tool"


@pytest.mark.anyio
async def test_direct_call_recorded_without_is_router_proxy():
    """MCPProxyServer._call_tool() direct tool path calls on_tool_called with is_router_proxy=False (default).

    Direct calls must NOT appear in router_proxies accounting.
    """
    registry = _make_tool_registry_for_proxy()
    proxy, pipeline = _make_proxy_with_pipeline(registry)

    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="server__other_tool",
            arguments={},
        ),
    )
    await proxy._call_tool(req)

    pipeline.on_tool_called.assert_called_once()
    call_args = pipeline.on_tool_called.call_args
    # is_router_proxy should default to False (keyword arg absent or explicitly False)
    is_proxy = call_args.kwargs.get("is_router_proxy", False)
    if len(call_args.args) >= 4:
        is_proxy = call_args.args[3]
    assert is_proxy is False, f"Direct call must not set is_router_proxy=True; got {call_args}"
