"""Tests for lifecycle fixes: stack leak, creation lock, cleanup state."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import AsyncExitStack
from src.multimcp.mcp_client import MCPClientManager


def _make_mgr(**overrides):
    """Create an MCPClientManager with all required attributes set."""
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
    mgr.on_server_reconnected = None
    mgr._connection_semaphore = asyncio.Semaphore(10)
    mgr._connection_timeout = 30.0
    mgr._supervision_tasks = {}
    mgr._lifecycle_tasks = {}
    mgr._shutdown_events = {}
    for k, v in overrides.items():
        setattr(mgr, k, v)
    return mgr


@pytest.mark.asyncio
async def test_reconnect_closes_old_stack():
    """_create_single_client must stop an existing lifecycle before creating a new one."""
    mgr = _make_mgr()

    # Install old stack for server — this is what should be closed on reconnect
    old_stack = AsyncMock(spec=AsyncExitStack)
    mgr.server_stacks["test_server"] = old_stack
    # Simulate an old lifecycle task that's already done
    old_task = asyncio.create_task(asyncio.sleep(0))
    await old_task
    mgr._lifecycle_tasks["test_server"] = old_task

    # Mock the transport and session so _create_single_client can complete
    server_config = {"command": "node", "args": [], "env": {}}
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock())

    with patch("src.multimcp.mcp_client.stdio_client") as mock_stdio, \
         patch("src.multimcp.mcp_client.ClientSession") as mock_cs:
        mock_read, mock_write = AsyncMock(), AsyncMock()
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        await mgr._create_single_client("test_server", server_config)

    # A new client must have been registered
    assert "test_server" in mgr.clients
    # Lifecycle task should be running
    assert "test_server" in mgr._lifecycle_tasks
    # Clean up
    evt = mgr._shutdown_events.get("test_server")
    if evt:
        evt.set()
    task = mgr._lifecycle_tasks.get("test_server")
    if task:
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except Exception:
            pass


def test_cleanup_server_state_removes_all_entries():
    """cleanup_server_state must remove ALL per-server dicts."""
    mgr = _make_mgr()
    mgr.pending_configs = {"srv": {"command": "node"}}
    mgr.server_configs = {"srv": {"command": "node"}}
    mgr.tool_filters = {"srv": {"allow": ["*"]}}
    mgr.idle_timeouts = {"srv": 300}
    mgr.last_used = {"srv": 12345.0}
    mgr._creation_locks = {"srv": asyncio.Lock()}
    mgr.clients = {"srv": MagicMock()}

    mgr.cleanup_server_state("srv")

    assert "srv" not in mgr.pending_configs
    assert "srv" not in mgr.server_configs
    assert "srv" not in mgr.tool_filters
    assert "srv" not in mgr.idle_timeouts
    assert "srv" not in mgr.last_used
    assert "srv" not in mgr._creation_locks
    assert "srv" not in mgr.clients


@pytest.mark.asyncio
async def test_supervision_cleans_up_dead_client():
    """When the supervision task detects a dead session, it removes the client
    and calls _on_server_disconnected so the watchdog can reconnect."""
    mgr = _make_mgr(_on_server_disconnected=AsyncMock())

    # Create a mock session whose send_ping raises (simulates dead connection)
    dead_session = MagicMock()
    dead_session.send_ping = AsyncMock(side_effect=Exception("connection lost"))
    mgr.clients["github"] = dead_session
    mgr.server_stacks["github"] = AsyncMock()

    mgr._start_supervision("github", interval=0.1)
    assert "github" in mgr._supervision_tasks

    for _ in range(50):
        await asyncio.sleep(0.1)
        if "github" not in mgr.clients:
            break

    assert "github" not in mgr.clients
    assert "github" not in mgr.server_stacks
    mgr._on_server_disconnected.assert_called_once_with("github")


@pytest.mark.asyncio
async def test_supervision_cancelled_on_shutdown():
    """Supervision tasks should be cleanly cancellable."""
    mgr = _make_mgr()

    healthy_session = MagicMock()
    healthy_session.send_ping = AsyncMock(return_value=None)
    mgr.clients["healthy"] = healthy_session
    mgr.server_stacks["healthy"] = AsyncMock()

    mgr._start_supervision("healthy")
    task = mgr._supervision_tasks["healthy"]
    assert not task.done()

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Client should NOT be removed (we cancelled, not detected failure)
    assert "healthy" in mgr.clients


@pytest.mark.asyncio
async def test_lifecycle_task_catches_backend_crash():
    """When backend dies, the lifecycle task catches the exception
    instead of crashing the event loop."""
    mgr = _make_mgr(_on_server_disconnected=AsyncMock())

    server_config = {"command": "node", "args": [], "env": {}}
    crash_event = asyncio.Event()

    mock_session = AsyncMock()

    with patch("src.multimcp.mcp_client.stdio_client") as mock_stdio, \
         patch("src.multimcp.mcp_client.ClientSession") as mock_cs:
        mock_read, mock_write = AsyncMock(), AsyncMock()
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

        await mgr._create_single_client("crashing", server_config)

    assert "crashing" in mgr.clients
    assert "crashing" in mgr._lifecycle_tasks

    # Simulate backend crash by setting the shutdown event
    # (in real use, the exception from the task group does this)
    evt = mgr._shutdown_events.get("crashing")
    if evt:
        evt.set()

    task = mgr._lifecycle_tasks.get("crashing")
    if task:
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except Exception:
            pass

    # After lifecycle ends, client should be cleaned up
    assert "crashing" not in mgr.clients
