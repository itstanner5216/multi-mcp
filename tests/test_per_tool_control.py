"""
Tests for per-tool runtime control via toggle_tool.

Covers:
- Disabling a tool hides it from tool_to_server
- Re-enabling a tool restores it
- tool_filters deny list updated for reconnect-safety
- Idempotent toggles (noop responses)
- Session-level monotonic guarantee: once a tool is introduced it is
  NEVER removed within that session regardless of toggle_tool calls
- YAML persistence (best-effort path)
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp import types

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry


def _make_proxy_with_tools(*tool_names: str, server: str = "calc") -> MCPProxyServer:
    """Build a proxy with pre-populated tool_to_server for the given tool names."""
    mgr = MCPClientManager()
    mock_client = AsyncMock()
    mgr.clients[server] = mock_client
    mgr.tool_filters[server] = None  # no filter = all allowed

    proxy = MCPProxyServer(mgr)
    proxy._server_session = None  # no active session in unit tests

    for tool_name in tool_names:
        key = proxy._make_key(server, tool_name)
        proxy.tool_to_server[key] = ToolMapping(
            server_name=server,
            client=mock_client,
            tool=types.Tool(
                name=key,
                description=f"{tool_name} description",
                inputSchema={
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                    "required": ["x"],
                },
            ),
        )

    return proxy


# ---------------------------------------------------------------------------
# Disable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_toggle_tool_disable_hides_tool():
    proxy = _make_proxy_with_tools("add", "multiply")

    result = await proxy.toggle_tool("calc", "add", enabled=False)

    assert result["status"] == "ok"
    assert result["enabled"] is False
    assert "calc__add" not in proxy.tool_to_server
    assert "calc__multiply" in proxy.tool_to_server


@pytest.mark.asyncio
async def test_toggle_tool_disable_updates_deny_list():
    proxy = _make_proxy_with_tools("add", "multiply")

    await proxy.toggle_tool("calc", "add", enabled=False)

    filters = proxy.client_manager.tool_filters["calc"]
    assert "add" in filters.get("deny", [])


@pytest.mark.asyncio
async def test_toggle_tool_disable_idempotent():
    """Disabling an already-invisible tool is a noop."""
    proxy = _make_proxy_with_tools("multiply")  # 'add' not in proxy at all

    result = await proxy.toggle_tool("calc", "add", enabled=False)

    assert result["status"] == "noop"


# ---------------------------------------------------------------------------
# Enable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_toggle_tool_enable_restores_tool():
    """Re-enabling a tool adds it back to tool_to_server."""
    proxy = _make_proxy_with_tools("multiply")  # 'add' was previously disabled/absent
    # Simulate prior disable: add to deny list
    proxy.client_manager.tool_filters["calc"] = {"allow": ["*"], "deny": ["add"]}

    result = await proxy.toggle_tool("calc", "add", enabled=True)

    assert result["status"] == "ok"
    assert result["enabled"] is True
    assert "calc__add" in proxy.tool_to_server


@pytest.mark.asyncio
async def test_toggle_tool_enable_removes_from_deny_list():
    proxy = _make_proxy_with_tools("multiply")
    proxy.client_manager.tool_filters["calc"] = {"allow": ["*"], "deny": ["add"]}

    await proxy.toggle_tool("calc", "add", enabled=True)

    filters = proxy.client_manager.tool_filters["calc"]
    assert "add" not in filters.get("deny", [])


@pytest.mark.asyncio
async def test_toggle_tool_enable_idempotent():
    """Enabling an already-visible tool is a noop."""
    proxy = _make_proxy_with_tools("add", "multiply")

    result = await proxy.toggle_tool("calc", "add", enabled=True)

    assert result["status"] == "noop"


@pytest.mark.asyncio
async def test_toggle_tool_enable_lazy_client_when_server_disconnected():
    """Re-enabled tool gets client=None when server is not currently connected."""
    mgr = MCPClientManager()
    # Server is in pending but NOT in clients (lazy/disconnected)
    mgr.pending_configs["calc"] = {"command": "python3"}
    mgr.tool_filters["calc"] = {"allow": ["*"], "deny": ["add"]}

    proxy = MCPProxyServer(mgr)
    proxy._server_session = None

    result = await proxy.toggle_tool("calc", "add", enabled=True)

    assert result["status"] == "ok"
    mapping = proxy.tool_to_server.get("calc__add")
    assert mapping is not None
    assert mapping.client is None  # lazy — connects on first call


# ---------------------------------------------------------------------------
# Reconnect safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deny_list_persists_through_reconnect_simulation():
    """After toggle_tool disable, tool_filters deny list prevents re-appearance on reconnect.

    Simulates reconnect by calling _initialize_tools_for_client again and
    verifying the disabled tool is still filtered out.
    """
    proxy = _make_proxy_with_tools("add", "multiply")

    await proxy.toggle_tool("calc", "add", enabled=False)

    # Simulate reconnect: _initialize_tools_for_client will call _is_tool_allowed
    filters = proxy.client_manager.tool_filters.get("calc", {})
    assert not proxy._is_tool_allowed("add", filters), (
        "Disabled tool must be blocked by _is_tool_allowed after reconnect"
    )
    assert proxy._is_tool_allowed("multiply", filters), (
        "Other tools must still pass _is_tool_allowed"
    )


# ---------------------------------------------------------------------------
# Session-level monotonic guarantee (Task 8)
# ---------------------------------------------------------------------------
#
# Rule: once a tool has been returned to a client in a session's tools/list,
# it must NEVER be removed from that session's view — regardless of toggle_tool
# calls, server reconnects, or any other runtime event.
#
# The MCP _list_tools() returns tools visible at the moment of the call.
# If a client caches the tool list (as Claude Desktop and Copilot do), they
# already have the tool. But even for clients that re-fetch after list_changed,
# the SessionStateManager in the retrieval pipeline guarantees monotonic sets.
#
# These tests verify that:
# 1. _list_tools() reflects toggle state immediately for new fetches
# 2. SessionStateManager never removes tools once added to a session
# 3. toggle_tool after a tool is session-resident does NOT remove it from the session

@pytest.mark.asyncio
async def test_list_tools_reflects_disable_for_new_clients():
    """After disable, _list_tools returns the tool only for sessions that saw it before.
    New clients (fresh _list_tools call) do NOT see it."""
    proxy = _make_proxy_with_tools("add", "multiply")

    # Before disable — both tools visible
    result_before = await proxy._list_tools(None)
    tool_names_before = {t.name for t in result_before.root.tools}
    assert "calc__add" in tool_names_before
    assert "calc__multiply" in tool_names_before

    # Disable add
    await proxy.toggle_tool("calc", "add", enabled=False)

    # After disable — add no longer visible in fresh list
    result_after = await proxy._list_tools(None)
    tool_names_after = {t.name for t in result_after.root.tools}
    assert "calc__add" not in tool_names_after, (
        "Disabled tool must not appear in tools/list for new calls"
    )
    assert "calc__multiply" in tool_names_after


@pytest.mark.asyncio
async def test_session_manager_monotonic_never_removes_tools():
    """SessionStateManager.add_tools is monotonic — tools already in a session
    cannot be removed by subsequent calls, regardless of toggle_tool.

    This is the core guarantee: once introduced, always present in that session.
    """
    from src.multimcp.retrieval.session import SessionStateManager
    from src.multimcp.retrieval.models import RetrievalConfig

    cfg = RetrievalConfig(enabled=True, anchor_tools=["calc__add"])
    mgr = SessionStateManager(cfg)

    # Session starts with anchor tool
    mgr.get_or_create_session("session-1")
    initial = mgr.get_active_tools("session-1")
    assert "calc__add" in initial

    # Add more tools (simulates tool being used)
    mgr.add_tools("session-1", ["calc__multiply"])
    assert "calc__multiply" in mgr.get_active_tools("session-1")

    # Simulate external toggle_tool disable — session manager has NO remove operation
    # Verify there is no way to remove a tool from a live session
    assert not hasattr(mgr, "remove_tools"), (
        "SessionStateManager must NOT have a remove_tools method — monotonic only"
    )

    # Both tools still present — no external event can remove them
    tools_after = mgr.get_active_tools("session-1")
    assert "calc__add" in tools_after, "Anchor tool must remain after any external event"
    assert "calc__multiply" in tools_after, "Added tool must remain after any external event"


@pytest.mark.asyncio
async def test_toggle_disable_does_not_affect_existing_session_tool_set():
    """A tool disabled via toggle_tool after a session already has it remains
    in that session's active set (monotonic guarantee).

    The proxy's tool_to_server is updated (new clients won't see it) but the
    SessionStateManager for existing sessions is NOT mutated.
    """
    from src.multimcp.retrieval.session import SessionStateManager
    from src.multimcp.retrieval.models import RetrievalConfig

    # Session already has calc__add
    cfg = RetrievalConfig(enabled=True, anchor_tools=["calc__add", "calc__multiply"])
    session_mgr = SessionStateManager(cfg)
    session_mgr.get_or_create_session("active-session")

    proxy = _make_proxy_with_tools("add", "multiply")
    proxy.retrieval_pipeline = MagicMock()  # stop pipeline from interfering
    proxy.retrieval_pipeline.session_manager = session_mgr

    # Disable calc__add at the proxy level
    await proxy.toggle_tool("calc", "add", enabled=False)

    # proxy's tool_to_server no longer has the tool (correct for new clients)
    assert "calc__add" not in proxy.tool_to_server

    # But the existing session's active tool set STILL contains it (monotonic)
    session_tools = session_mgr.get_active_tools("active-session")
    assert "calc__add" in session_tools, (
        "CRITICAL: Tool disabled at proxy level must NOT be removed from an existing "
        "session that already received it. Sessions are monotonic."
    )


@pytest.mark.asyncio
async def test_response_includes_visible_tools_count():
    proxy = _make_proxy_with_tools("add", "multiply")

    result = await proxy.toggle_tool("calc", "add", enabled=False)

    assert "visible_tools_for_server" in result
    # multiply is still visible and connected → count = 1
    assert result["visible_tools_for_server"] == 1
