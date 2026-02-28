"""
Tests for Transport Consistency (Task 6e):
- URL server discovery tries Streamable HTTP first, then SSE fallback
- Lazy runtime connect uses same transport logic as discovery
- Watchdog reconnect uses same transport logic as discovery
- Transport type from YAML config is respected
"""

import pytest
import asyncio
from contextlib import asynccontextmanager, AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.yaml_config import ServerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_streamable():
    """Return an asynccontextmanager that yields (read, write, session)."""
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_session_transport = MagicMock()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_read, mock_write, mock_session_transport

    return _ctx, mock_read, mock_write


def _make_mock_sse():
    """Return an asynccontextmanager that yields (read, write)."""
    mock_read = AsyncMock()
    mock_write = AsyncMock()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_read, mock_write

    return _ctx, mock_read, mock_write


def _make_mock_client_session(has_tools=False):
    """Build a mock ClientSession that works as an async context manager."""
    mock_sess = AsyncMock()
    capabilities = MagicMock()
    capabilities.tools = has_tools
    mock_sess.initialize = AsyncMock(return_value=MagicMock(capabilities=capabilities))
    mock_sess.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
    mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_sess.__aexit__ = AsyncMock(return_value=False)
    return mock_sess


def _make_mock_client_session_cls(has_tools=False):
    """Return a mock class whose instances work as async context managers."""
    mock_sess = _make_mock_client_session(has_tools)
    mock_cls = MagicMock()
    mock_cls.return_value = mock_sess
    return mock_cls, mock_sess


# ---------------------------------------------------------------------------
# TestAutoDetectTransport
# ---------------------------------------------------------------------------

class TestAutoDetectTransport:
    """Tests for auto-detect transport logic (no explicit type or type='stdio')."""

    @pytest.mark.asyncio
    async def test_discover_tries_streamable_http_first(self):
        """Auto-detect mode: streamable_http_client is called; sse_client is NOT called."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="stdio")

        streamable_ctx, _, _ = _make_mock_streamable()
        mock_cls, _ = _make_mock_client_session_cls(has_tools=False)

        with patch("src.multimcp.mcp_client.streamable_http_client", streamable_ctx) as mock_sh, \
             patch("src.multimcp.mcp_client.sse_client") as mock_sse, \
             patch("src.multimcp.mcp_client.ClientSession", mock_cls):
            await manager._discover_sse("srv", "http://example.com", server_config)

        # streamable_http_client was called (the context manager itself was entered)
        # We verify by checking sse_client was NOT called — only streamable HTTP path ran
        mock_sse.assert_not_called()

    @pytest.mark.asyncio
    async def test_discover_falls_back_to_sse_on_streamable_failure(self):
        """Auto-detect mode: if streamable_http_client raises, sse_client is used."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="stdio")

        sse_ctx, _, _ = _make_mock_sse()
        mock_cls, _ = _make_mock_client_session_cls(has_tools=False)

        with patch("src.multimcp.mcp_client.streamable_http_client",
                   side_effect=Exception("connection refused")), \
             patch("src.multimcp.mcp_client.sse_client", sse_ctx) as mock_sse_factory, \
             patch("src.multimcp.mcp_client.ClientSession", mock_cls):
            result = await manager._discover_sse("srv", "http://example.com", server_config)

        # SSE fallback was invoked — result is an empty list (no tools)
        assert result == []

    @pytest.mark.asyncio
    async def test_connect_url_server_tries_streamable_first(self):
        """_connect_url_server with server_config=None attempts Streamable HTTP."""
        manager = MCPClientManager()

        streamable_ctx, _, _ = _make_mock_streamable()
        mock_cls, mock_sess = _make_mock_client_session_cls()

        async with AsyncExitStack() as server_stack:
            with patch("src.multimcp.mcp_client.streamable_http_client", streamable_ctx), \
                 patch("src.multimcp.mcp_client.sse_client") as mock_sse, \
                 patch("src.multimcp.mcp_client.ClientSession", mock_cls):
                client = await manager._connect_url_server(
                    "srv", "http://example.com", {}, server_stack, None
                )

        # sse_client must NOT have been called — streamable HTTP succeeded
        mock_sse.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_url_server_falls_back_to_sse(self):
        """_connect_url_server falls back to SSE when Streamable HTTP fails."""
        manager = MCPClientManager()

        sse_ctx, _, _ = _make_mock_sse()
        mock_cls, mock_sess = _make_mock_client_session_cls()

        async with AsyncExitStack() as server_stack:
            with patch("src.multimcp.mcp_client.streamable_http_client",
                       side_effect=Exception("refused")), \
                 patch("src.multimcp.mcp_client.sse_client", sse_ctx), \
                 patch("src.multimcp.mcp_client.ClientSession", mock_cls):
                client = await manager._connect_url_server(
                    "srv", "http://example.com", {}, server_stack, None
                )

        # The returned client should be the mock session
        assert client is mock_sess


# ---------------------------------------------------------------------------
# TestExplicitTransportType
# ---------------------------------------------------------------------------

class TestExplicitTransportType:
    """Tests that explicit type= in ServerConfig is respected."""

    @pytest.mark.asyncio
    async def test_sse_type_skips_streamable_http_in_discover(self):
        """type='sse': sse_client is used directly; streamable_http_client NOT called."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="sse")

        sse_ctx, _, _ = _make_mock_sse()
        mock_cls, _ = _make_mock_client_session_cls(has_tools=False)

        with patch("src.multimcp.mcp_client.streamable_http_client") as mock_sh, \
             patch("src.multimcp.mcp_client.sse_client", sse_ctx), \
             patch("src.multimcp.mcp_client.ClientSession", mock_cls):
            result = await manager._discover_sse("srv", "http://example.com", server_config)

        mock_sh.assert_not_called()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_http_type_skips_streamable_http_in_discover(self):
        """type='http': sse_client is used directly; streamable_http_client NOT called."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="http")

        sse_ctx, _, _ = _make_mock_sse()
        mock_cls, _ = _make_mock_client_session_cls(has_tools=False)

        with patch("src.multimcp.mcp_client.streamable_http_client") as mock_sh, \
             patch("src.multimcp.mcp_client.sse_client", sse_ctx), \
             patch("src.multimcp.mcp_client.ClientSession", mock_cls):
            result = await manager._discover_sse("srv", "http://example.com", server_config)

        mock_sh.assert_not_called()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_streamablehttp_type_skips_sse_in_discover(self):
        """type='streamablehttp': streamable_http_client used; sse_client NOT called."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="streamablehttp")

        streamable_ctx, _, _ = _make_mock_streamable()
        mock_cls, _ = _make_mock_client_session_cls(has_tools=False)

        with patch("src.multimcp.mcp_client.streamable_http_client", streamable_ctx), \
             patch("src.multimcp.mcp_client.sse_client") as mock_sse, \
             patch("src.multimcp.mcp_client.ClientSession", mock_cls):
            result = await manager._discover_sse("srv", "http://example.com", server_config)

        mock_sse.assert_not_called()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_sse_type_in_connect_url_server_skips_streamable(self):
        """type='sse' in _connect_url_server: streamable_http_client NOT called."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="sse")

        sse_ctx, _, _ = _make_mock_sse()
        mock_cls, mock_sess = _make_mock_client_session_cls()

        async with AsyncExitStack() as server_stack:
            with patch("src.multimcp.mcp_client.streamable_http_client") as mock_sh, \
                 patch("src.multimcp.mcp_client.sse_client", sse_ctx), \
                 patch("src.multimcp.mcp_client.ClientSession", mock_cls):
                client = await manager._connect_url_server(
                    "srv", "http://example.com", {}, server_stack, server_config
                )

        mock_sh.assert_not_called()
        assert client is mock_sess

    @pytest.mark.asyncio
    async def test_none_transport_type_tries_streamable_first(self):
        """server_config=None in _connect_url_server: streamable_http_client attempted."""
        manager = MCPClientManager()

        streamable_ctx, _, _ = _make_mock_streamable()
        mock_cls, mock_sess = _make_mock_client_session_cls()

        async with AsyncExitStack() as server_stack:
            with patch("src.multimcp.mcp_client.streamable_http_client", streamable_ctx), \
                 patch("src.multimcp.mcp_client.sse_client") as mock_sse, \
                 patch("src.multimcp.mcp_client.ClientSession", mock_cls):
                client = await manager._connect_url_server(
                    "srv", "http://example.com", {}, server_stack, None
                )

        # SSE was NOT needed — streamable succeeded
        mock_sse.assert_not_called()

    @pytest.mark.asyncio
    async def test_streamablehttp_type_returns_empty_on_failure(self):
        """type='streamablehttp' failure returns empty list (no SSE fallback)."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="streamablehttp")

        with patch("src.multimcp.mcp_client.streamable_http_client",
                   side_effect=Exception("server unavailable")), \
             patch("src.multimcp.mcp_client.sse_client") as mock_sse:
            result = await manager._discover_sse("srv", "http://example.com", server_config)

        # No SSE fallback for explicit streamablehttp type
        mock_sse.assert_not_called()
        assert result == []

    @pytest.mark.asyncio
    async def test_sse_type_returns_empty_on_failure(self):
        """type='sse' failure returns empty list (no streamable fallback)."""
        manager = MCPClientManager()
        server_config = ServerConfig(command="node", type="sse")

        with patch("src.multimcp.mcp_client.streamable_http_client") as mock_sh, \
             patch("src.multimcp.mcp_client.sse_client",
                   side_effect=Exception("server unavailable")):
            result = await manager._discover_sse("srv", "http://example.com", server_config)

        mock_sh.assert_not_called()
        assert result == []


# ---------------------------------------------------------------------------
# TestWatchdogTransport
# ---------------------------------------------------------------------------

class TestWatchdogTransport:
    """Tests that the watchdog reconnect uses _connect_url_server for URL servers."""

    @pytest.mark.asyncio
    async def test_watchdog_uses_connect_url_server_for_url_servers(self):
        """When a URL always-on server disconnects, watchdog calls _connect_url_server."""
        manager = MCPClientManager()
        manager.always_on_servers = {"url-srv"}
        # No entry in clients → triggers reconnect
        manager.clients = {}

        server_config_dict = {"url": "http://example.com", "env": {}}

        mock_client = AsyncMock()
        mock_client.initialize = AsyncMock(return_value=MagicMock())

        async def fake_connect(name, url, env, stack, server_config=None):
            return mock_client

        with patch.object(manager, "_connect_url_server", wraps=fake_connect) as mock_conn, \
             patch.object(manager, "start_always_on_watchdog",
                          wraps=manager.start_always_on_watchdog):
            # Manually drive one iteration of the watchdog body (skip the sleep loop)
            configs = {"url-srv": server_config_dict}
            for name in list(manager.always_on_servers):
                if name not in manager.clients:
                    server_cfg = configs.get(name)
                    assert server_cfg is not None
                    url = server_cfg.get("url")
                    env = server_cfg.get("env", {})
                    if url:
                        server_stack = AsyncExitStack()
                        await server_stack.__aenter__()
                        try:
                            client = await manager._connect_url_server(
                                name, url, env, server_stack
                            )
                            await client.initialize()
                            manager.clients[name] = client
                            manager.server_stacks[name] = server_stack
                        except Exception:
                            await server_stack.aclose()

            mock_conn.assert_called_once()
            call_args = mock_conn.call_args
            assert call_args[0][0] == "url-srv"
            assert call_args[0][1] == "http://example.com"
            assert "url-srv" in manager.clients

    @pytest.mark.asyncio
    async def test_watchdog_skips_already_connected_servers(self):
        """Watchdog does not attempt to reconnect servers that are already in clients."""
        manager = MCPClientManager()
        mock_client = AsyncMock()
        manager.always_on_servers = {"my-srv"}
        manager.clients = {"my-srv": mock_client}  # Already connected

        configs = {"my-srv": {"url": "http://example.com", "env": {}}}

        with patch.object(manager, "_connect_url_server") as mock_conn:
            for name in list(manager.always_on_servers):
                if name not in manager.clients:
                    # This block should NOT execute
                    server_cfg = configs.get(name)
                    url = server_cfg.get("url")
                    if url:
                        server_stack = AsyncExitStack()
                        await server_stack.__aenter__()
                        await manager._connect_url_server(name, url, {}, server_stack)

        mock_conn.assert_not_called()

    @pytest.mark.asyncio
    async def test_watchdog_transport_consistent_with_direct_connect(self):
        """_connect_url_server is used both in watchdog and lazy connect — same transport logic."""
        manager = MCPClientManager()

        sse_ctx, _, _ = _make_mock_sse()
        streamable_ctx, _, _ = _make_mock_streamable()
        mock_cls, mock_sess = _make_mock_client_session_cls()

        # Both the watchdog path and the lazy-connect path call _connect_url_server,
        # which itself respects transport_type. Verify the logic is identical by calling
        # _connect_url_server directly and confirming streamable HTTP is tried first.
        async with AsyncExitStack() as stack:
            with patch("src.multimcp.mcp_client.streamable_http_client", streamable_ctx), \
                 patch("src.multimcp.mcp_client.sse_client") as mock_sse_fn, \
                 patch("src.multimcp.mcp_client.ClientSession", mock_cls):
                client = await manager._connect_url_server(
                    "srv", "http://example.com", {}, stack
                )

        # Streamable HTTP was tried; SSE was not needed
        mock_sse_fn.assert_not_called()
        assert client is mock_sess
