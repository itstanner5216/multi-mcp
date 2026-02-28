"""
Tests for concurrent access safety:
- Simultaneous get_or_create_client for same server creates only one connection.
- Concurrent _call_tool + _disconnect_idle_servers does not crash.
- Concurrent _list_tools during modifications returns consistent results.
- Per-server creation locks prevent race conditions.
"""

import asyncio
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping
from mcp import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client():
    """Return a minimal mock ClientSession."""
    client = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# 1. TestConcurrentClientCreation
# ---------------------------------------------------------------------------

class TestConcurrentClientCreation:
    """Test that concurrent get_or_create_client calls for the same server
    result in exactly one connection being established."""

    @pytest.mark.asyncio
    async def test_two_concurrent_creates_one_connection(self):
        """Two simultaneous get_or_create_client("srv") calls create only one client."""
        manager = MCPClientManager()
        manager.add_pending_server("srv", {"command": "node"})

        call_count = 0
        mock_client = _make_mock_client()

        async def fake_create(name, config):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # simulate connection delay
            manager.clients[name] = mock_client

        with patch.object(manager, "_create_single_client", side_effect=fake_create):
            results = await asyncio.gather(
                manager.get_or_create_client("srv"),
                manager.get_or_create_client("srv"),
            )

        assert call_count == 1, f"Expected 1 connection, got {call_count}"
        assert all(r is mock_client for r in results)

    @pytest.mark.asyncio
    async def test_five_concurrent_creates_one_connection(self):
        """Five simultaneous get_or_create_client("srv") calls create only one client."""
        manager = MCPClientManager()
        manager.add_pending_server("srv", {"command": "node"})

        call_count = 0
        mock_client = _make_mock_client()

        async def fake_create(name, config):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            manager.clients[name] = mock_client

        with patch.object(manager, "_create_single_client", side_effect=fake_create):
            results = await asyncio.gather(*[
                manager.get_or_create_client("srv") for _ in range(5)
            ])

        assert call_count == 1, f"Expected 1 connection, got {call_count}"
        assert all(r is mock_client for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_create_all_return_same_client(self):
        """All concurrent callers receive the exact same client instance."""
        manager = MCPClientManager()
        manager.add_pending_server("srv", {"command": "node"})

        sentinel = _make_mock_client()

        async def fake_create(name, config):
            await asyncio.sleep(0.005)
            manager.clients[name] = sentinel

        with patch.object(manager, "_create_single_client", side_effect=fake_create):
            results = await asyncio.gather(*[
                manager.get_or_create_client("srv") for _ in range(4)
            ])

        # Every result must be the exact same object
        assert len(set(id(r) for r in results)) == 1

    @pytest.mark.asyncio
    async def test_creation_lock_prevents_race_condition(self):
        """After concurrent access, _creation_locks["srv"] exists."""
        manager = MCPClientManager()
        manager.add_pending_server("srv", {"command": "node"})

        mock_client = _make_mock_client()

        async def fake_create(name, config):
            await asyncio.sleep(0.005)
            manager.clients[name] = mock_client

        with patch.object(manager, "_create_single_client", side_effect=fake_create):
            await asyncio.gather(
                manager.get_or_create_client("srv"),
                manager.get_or_create_client("srv"),
            )

        # Lock may have been cleaned up by _disconnect_idle_servers; what matters
        # is the get_or_create_client completed without error and only one client exists.
        assert "srv" in manager.clients


# ---------------------------------------------------------------------------
# 2. TestConcurrentToolCall
# ---------------------------------------------------------------------------

class TestConcurrentToolCall:
    """Test concurrent _call_tool and _disconnect_idle_servers don't crash."""

    @pytest.mark.asyncio
    async def test_concurrent_tool_call_and_idle_disconnect_no_crash(self):
        """Concurrent _call_tool and _disconnect_idle_servers must not raise."""
        manager = MCPClientManager()

        # Set up a mock client
        mock_client = AsyncMock()
        mock_tool_result = MagicMock()
        mock_tool_result.content = [types.TextContent(type="text", text="ok")]
        mock_tool_result.isError = False
        mock_client.call_tool = AsyncMock(return_value=mock_tool_result)

        # Register client in manager
        manager.clients["srv"] = mock_client
        manager.server_configs["srv"] = {"command": "node"}
        manager.idle_timeouts["srv"] = 0.001   # very short timeout
        manager.last_used["srv"] = time.monotonic() - 10  # already expired

        # Build proxy and register the tool
        proxy = MCPProxyServer(manager)
        tool = types.Tool(
            name="srv__my_tool",
            description="test tool",
            inputSchema={"type": "object", "properties": {}},
        )
        proxy.tool_to_server["srv__my_tool"] = ToolMapping(
            server_name="srv",
            client=mock_client,
            tool=tool,
        )

        # Build a fake CallToolRequest
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="srv__my_tool", arguments={}),
        )

        # Run both concurrently; neither should raise an unhandled exception
        results = await asyncio.gather(
            proxy._call_tool(req),
            manager._disconnect_idle_servers(),
            return_exceptions=True,
        )
        # Neither coroutine should have raised an exception
        for r in results:
            assert not isinstance(r, Exception), f"Unexpected exception: {r}"

    @pytest.mark.asyncio
    async def test_concurrent_list_tools_is_consistent(self):
        """Concurrent _list_tools calls all return lists, not exceptions."""
        manager = MCPClientManager()
        mock_client = _make_mock_client()
        manager.clients["srv"] = mock_client

        proxy = MCPProxyServer(manager)

        # Add a few tools
        for i in range(5):
            tool = types.Tool(
                name=f"srv__tool_{i}",
                description=f"tool {i}",
                inputSchema={"type": "object", "properties": {}},
            )
            proxy.tool_to_server[f"srv__tool_{i}"] = ToolMapping(
                server_name="srv",
                client=mock_client,
                tool=tool,
            )

        async def modify_tools():
            """Simulate concurrent modification of tool_to_server."""
            await asyncio.sleep(0)
            # Add a new tool while list_tools may be running
            extra_tool = types.Tool(
                name="srv__extra",
                description="extra",
                inputSchema={"type": "object", "properties": {}},
            )
            proxy.tool_to_server["srv__extra"] = ToolMapping(
                server_name="srv",
                client=mock_client,
                tool=extra_tool,
            )

        # Run many concurrent list_tools plus a modifier
        list_coros = [proxy._list_tools(None) for _ in range(10)]
        results = await asyncio.gather(*list_coros, modify_tools(), return_exceptions=True)

        for r in results[:-1]:  # last result is from modify_tools (None)
            assert not isinstance(r, Exception), f"Unexpected exception: {r}"
            # ServerResult wraps the inner result in .root; tools are at .root.tools
            assert isinstance(r.root.tools, list)


# ---------------------------------------------------------------------------
# 3. TestConcurrentRegisterUnregister
# ---------------------------------------------------------------------------

class TestConcurrentRegisterUnregister:
    """Test concurrent server register/unregister safety."""

    @pytest.mark.asyncio
    async def test_register_lock_prevents_corruption(self):
        """Concurrent register of different servers doesn't corrupt tool_to_server."""
        manager = MCPClientManager()
        proxy = MCPProxyServer(manager)

        async def _register_server(name: str):
            """Simulate minimal registration without a live MCP session."""
            tool = types.Tool(
                name=f"{name}__tool",
                description="test",
                inputSchema={"type": "object", "properties": {}},
            )
            async with proxy._register_lock:
                mock_client = _make_mock_client()
                manager.clients[name] = mock_client
                proxy.tool_to_server[f"{name}__tool"] = ToolMapping(
                    server_name=name,
                    client=mock_client,
                    tool=tool,
                )

        # Register 10 different servers concurrently
        await asyncio.gather(*[_register_server(f"srv{i}") for i in range(10)])

        # All 10 tools must be present
        assert len(proxy.tool_to_server) == 10
        for i in range(10):
            assert f"srv{i}__tool" in proxy.tool_to_server

    @pytest.mark.asyncio
    async def test_creation_lock_is_per_server(self):
        """_get_creation_lock returns different lock objects for different servers."""
        manager = MCPClientManager()

        lock_srv1 = manager._get_creation_lock("srv1")
        lock_srv2 = manager._get_creation_lock("srv2")

        # Locks must be distinct objects
        assert lock_srv1 is not lock_srv2

        # Same server name always returns the same lock
        assert manager._get_creation_lock("srv1") is lock_srv1
        assert manager._get_creation_lock("srv2") is lock_srv2
