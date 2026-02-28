"""Tests for lifecycle fixes: stack leak, creation lock, cleanup state."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from contextlib import AsyncExitStack
from src.multimcp.mcp_client import MCPClientManager


@pytest.mark.asyncio
async def test_reconnect_closes_old_stack():
    """_create_single_client must close an existing stack before creating a new one."""
    from unittest.mock import patch, AsyncMock, MagicMock
    import asyncio
    from contextlib import AsyncExitStack
    from src.multimcp.mcp_client import MCPClientManager

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

    # Install old stack for server — this is what should be closed on reconnect
    old_stack = AsyncMock(spec=AsyncExitStack)
    mgr.server_stacks["test_server"] = old_stack

    # Mock the transport and session so _create_single_client can complete
    server_config = {"command": "node", "args": [], "env": {}}
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock())

    with patch("src.multimcp.mcp_client.stdio_client") as mock_stdio, \
         patch("src.multimcp.mcp_client.ClientSession") as mock_cs:
        # Make stdio_client an async context manager that yields (read, write)
        mock_read, mock_write = AsyncMock(), AsyncMock()
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)

        # Make ClientSession an async context manager that yields the session
        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        await mgr._create_single_client("test_server", server_config)

    # The old stack MUST have been closed before creating the new client
    old_stack.aclose.assert_called_once()
    # And a new stack must have been registered
    assert "test_server" in mgr.server_stacks
    assert mgr.server_stacks["test_server"] is not old_stack


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
    mgr.clients = {"srv": MagicMock()}
    mgr.logger = MagicMock()

    mgr.cleanup_server_state("srv")

    assert "srv" not in mgr.pending_configs
    assert "srv" not in mgr.server_configs
    assert "srv" not in mgr.tool_filters
    assert "srv" not in mgr.idle_timeouts
    assert "srv" not in mgr.last_used
    assert "srv" not in mgr._creation_locks
    assert "srv" not in mgr.clients
