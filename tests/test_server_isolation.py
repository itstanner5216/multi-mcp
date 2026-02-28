"""
Tests for graceful failure isolation and the tool circuit breaker.

Covers:
1. initialize_single_client timeout — hanging server doesn't block indefinitely
2. Trigger path isolation — unprotected initialize_single_client was a kill path
3. Circuit breaker — consecutive transport failures auto-quarantine the tool
4. Circuit breaker reset on success — transient failures don't accumulate
5. isError responses do NOT trigger quarantine (only transport exceptions do)
6. Auto-quarantine fires toggle_tool, tool disappears from tool_to_server
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from mcp import types
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping


def _proxy_with_mock_client(
    server: str = "srv", tool: str = "tool", connected: bool = True
) -> tuple[MCPProxyServer, AsyncMock]:
    """Build a proxy with one tool mapped to a mock client."""
    mgr = MCPClientManager()
    mock_client = AsyncMock() if connected else None
    if connected:
        mgr.clients[server] = mock_client
    mgr.tool_filters[server] = None
    proxy = MCPProxyServer(mgr)
    proxy._server_session = None

    key = proxy._make_key(server, tool)
    proxy.tool_to_server[key] = ToolMapping(
        server_name=server,
        client=mock_client,
        tool=types.Tool(
            name=key,
            description="test tool",
            inputSchema={"type": "object", "properties": {}},
        ),
    )
    return proxy, mock_client


# ---------------------------------------------------------------------------
# Fix 1: initialize_single_client has timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_single_client_respects_timeout():
    """initialize_single_client must timeout instead of hanging forever.

    Root cause: await client.initialize() had no asyncio.wait_for wrapper.
    A server that connects but hangs during the MCP initialize handshake
    would block the call coroutine indefinitely.
    """
    mgr = MCPClientManager(connection_timeout=0.1)  # very short for test
    proxy = MCPProxyServer(mgr)

    hung_client = AsyncMock()

    async def _hang_forever():
        await asyncio.sleep(9999)

    hung_client.initialize = _hang_forever

    with pytest.raises(asyncio.TimeoutError):
        await proxy.initialize_single_client("slow_server", hung_client)


@pytest.mark.asyncio
async def test_initialize_single_client_fast_success():
    """Normal initialize completes under timeout — not broken by the fix."""
    mgr = MCPClientManager(connection_timeout=5.0)
    proxy = MCPProxyServer(mgr)

    fast_client = AsyncMock()
    fast_client.initialize.return_value = MagicMock(
        capabilities=MagicMock(tools=None, prompts=None, resources=None)
    )

    # Should not raise
    await proxy.initialize_single_client("fast_server", fast_client)
    fast_client.initialize.assert_called_once()


# ---------------------------------------------------------------------------
# Fix 2: Trigger path is now protected (was an unhandled exception kill path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_path_exception_does_not_propagate():
    """initialize_single_client failure during trigger-activation must NOT
    propagate out of _call_tool and kill the session.

    Root cause: lines 373-377 called initialize_single_client without try/except.
    If it raised (e.g. ValueError for server name, list_tools failure), the
    exception reached the anyio task group and killed the stdio session.
    """
    proxy, mock_client = _proxy_with_mock_client("srv", "tool")

    # Trigger manager fires, returns a server that then fails to initialize
    proxy.trigger_manager = AsyncMock()
    proxy.trigger_manager.check_and_enable = AsyncMock(return_value=["bad_server"])
    proxy.client_manager.clients["bad_server"] = AsyncMock()

    # initialize_single_client raises for bad_server
    original_init = proxy.initialize_single_client

    async def patched_init(name, client):
        if name == "bad_server":
            raise ValueError("Server name 'bad__server' cannot contain '__' separator")
        return await original_init(name, client)

    proxy.initialize_single_client = patched_init

    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="srv__tool", arguments={}),
    )

    mock_client.call_tool.return_value = MagicMock(
        content=[MagicMock(text="42")], isError=False
    )

    # Must not raise — must return a result (even if tool call itself works)
    result = await proxy._call_tool(req)
    assert result is not None  # didn't crash the proxy


# ---------------------------------------------------------------------------
# Fix 3: Circuit breaker — transport failures → auto-quarantine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_quarantines_after_threshold():
    """After quarantine_threshold consecutive transport failures, the tool
    must be auto-quarantined (removed from tool_to_server).

    Only transport exceptions (call_tool raises) trigger this — NOT isError responses.
    """
    proxy, mock_client = _proxy_with_mock_client("srv", "crashing_tool")
    proxy.quarantine_threshold = 3

    # Make call_tool raise a transport exception each time
    mock_client.call_tool = AsyncMock(side_effect=ConnectionError("subprocess died"))

    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="srv__crashing_tool", arguments={}),
    )

    # First two failures — tool still visible
    await proxy._call_tool(req)
    assert "srv__crashing_tool" in proxy.tool_to_server, "Tool should still be visible after 1 failure"
    await proxy._call_tool(req)
    assert "srv__crashing_tool" in proxy.tool_to_server, "Tool should still be visible after 2 failures"

    # Third failure — triggers auto-quarantine
    result = await proxy._call_tool(req)

    assert "srv__crashing_tool" not in proxy.tool_to_server, (
        "Tool must be auto-quarantined after 3 consecutive transport failures"
    )
    assert result.root.isError  # error still returned to caller


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success():
    """A successful call resets the failure counter — transient failures
    don't accumulate across unrelated calls.
    """
    proxy, mock_client = _proxy_with_mock_client("srv", "flaky_tool")
    proxy.quarantine_threshold = 3

    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="srv__flaky_tool", arguments={}),
    )

    # Two failures
    mock_client.call_tool = AsyncMock(side_effect=ConnectionError("died"))
    await proxy._call_tool(req)
    await proxy._call_tool(req)
    assert proxy._tool_failure_counts.get("srv__flaky_tool", 0) == 2

    # Success — resets the counter
    mock_client.call_tool = AsyncMock(return_value=types.CallToolResult(
        content=[types.TextContent(type="text", text="ok")], isError=False
    ))
    await proxy._call_tool(req)
    assert proxy._tool_failure_counts.get("srv__flaky_tool", 0) == 0, (
        "Counter must reset to 0 on success"
    )

    # Tool is still visible (not quarantined)
    assert "srv__flaky_tool" in proxy.tool_to_server


@pytest.mark.asyncio
async def test_circuit_breaker_does_not_trigger_on_is_error_response():
    """isError=True tool responses must NOT trigger the circuit breaker.

    These are tool-level responses (e.g. 'invalid argument', 'not found') and
    could be caused by the CALLER passing wrong arguments — not a broken tool.
    Only transport-level exceptions (call_tool raises) trigger quarantine.
    """
    proxy, mock_client = _proxy_with_mock_client("srv", "strict_tool")
    proxy.quarantine_threshold = 3

    # Tool consistently returns isError=True (caller's bad arguments scenario)
    mock_client.call_tool = AsyncMock(return_value=types.CallToolResult(
        content=[types.TextContent(type="text", text="Invalid argument: x must be positive")],
        isError=True,
    ))

    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="srv__strict_tool", arguments={"x": -1}),
    )

    # Call many times with bad arguments — tool must NOT be quarantined
    for _ in range(10):
        await proxy._call_tool(req)

    assert "srv__strict_tool" in proxy.tool_to_server, (
        "Tool must NOT be quarantined for isError=True responses — "
        "those could be valid argument validation errors from the caller"
    )
    assert proxy._tool_failure_counts.get("srv__strict_tool", 0) == 0, (
        "isError responses must not increment failure counter"
    )


@pytest.mark.asyncio
async def test_circuit_breaker_independent_per_tool():
    """Failures on one tool must not affect the counter for other tools."""
    proxy, mock_client = _proxy_with_mock_client("srv", "bad_tool")
    proxy.quarantine_threshold = 3

    # Add a second good tool
    key2 = "srv__good_tool"
    proxy.tool_to_server[key2] = ToolMapping(
        server_name="srv",
        client=mock_client,
        tool=types.Tool(name=key2, description="", inputSchema={"type": "object", "properties": {}}),
    )

    bad_req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="srv__bad_tool", arguments={}),
    )

    mock_client.call_tool = AsyncMock(side_effect=RuntimeError("crash"))

    # Fail bad_tool 3 times → quarantine
    for _ in range(3):
        await proxy._call_tool(bad_req)

    assert "srv__bad_tool" not in proxy.tool_to_server
    assert "srv__good_tool" in proxy.tool_to_server, (
        "Other tools must NOT be affected by one tool's circuit breaker"
    )
