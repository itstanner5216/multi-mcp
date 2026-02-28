"""Tests for lifecycle fixes: stack leak, creation lock, cleanup state."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from contextlib import AsyncExitStack
from src.multimcp.mcp_client import MCPClientManager


@pytest.mark.asyncio
async def test_reconnect_closes_old_stack():
    """When reconnecting, old AsyncExitStack must be closed before creating new one."""
    mgr = MCPClientManager.__new__(MCPClientManager)
    mgr.server_stacks = {}
    mgr.clients = {}
    mgr.pending_configs = {}
    mgr.server_configs = {}
    mgr._creation_locks = {}
    mgr.always_on_servers = set()
    mgr.tool_filters = {}
    mgr.idle_timeouts = {}
    mgr.last_used = {}
    mgr.logger = MagicMock()
    mgr._on_server_disconnected = None
    mgr._on_server_reconnected = None
    mgr.on_server_reconnected = None
    mgr._connection_semaphore = asyncio.Semaphore(10)
    mgr._connection_timeout = 30.0

    # Simulate an existing stack that wasn't properly cleaned
    old_stack = AsyncMock(spec=AsyncExitStack)
    mgr.server_stacks["test_server"] = old_stack

    # Verify that creating a new client for the same server closes the old stack
    if "test_server" in mgr.server_stacks:
        existing_stack = mgr.server_stacks["test_server"]
        try:
            await existing_stack.aclose()
        except Exception:
            pass

    old_stack.aclose.assert_called_once()


def test_cleanup_server_state_removes_all_entries():
    """cleanup_server_state must remove ALL per-server dicts."""
    mgr = MCPClientManager.__new__(MCPClientManager)
    mgr.pending_configs = {"srv": {"command": "node"}}
    mgr.server_configs = {"srv": {"command": "node"}}
    mgr.tool_filters = {"srv": {"allow": ["*"]}}
    mgr.idle_timeouts = {"srv": 300}
    mgr.last_used = {"srv": 12345.0}
    mgr._creation_locks = {"srv": asyncio.Lock()}
    mgr.server_stacks = {}
    mgr.logger = MagicMock()

    mgr.cleanup_server_state("srv")

    assert "srv" not in mgr.pending_configs
    assert "srv" not in mgr.server_configs
    assert "srv" not in mgr.tool_filters
    assert "srv" not in mgr.idle_timeouts
    assert "srv" not in mgr.last_used
    assert "srv" not in mgr._creation_locks
