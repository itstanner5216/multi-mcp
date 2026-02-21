import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from src.multimcp.mcp_client import MCPClientManager

@pytest.mark.asyncio
async def test_record_usage_updates_timestamp():
    manager = MCPClientManager()
    before = time.monotonic()
    manager.record_usage("exa")
    after = time.monotonic()
    assert before <= manager.last_used["exa"] <= after

@pytest.mark.asyncio
async def test_idle_servers_are_disconnected():
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["tavily"] = mock_session
    manager.always_on_servers = set()
    manager.idle_timeouts["tavily"] = 0.01  # 10ms timeout for test
    manager.last_used["tavily"] = time.monotonic() - 1.0  # 1 second ago

    await manager._disconnect_idle_servers()

    assert "tavily" not in manager.clients

@pytest.mark.asyncio
async def test_always_on_servers_not_disconnected():
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["github"] = mock_session
    manager.always_on_servers = {"github"}
    manager.idle_timeouts["github"] = 0.01
    manager.last_used["github"] = time.monotonic() - 1.0

    await manager._disconnect_idle_servers()

    assert "github" in manager.clients

@pytest.mark.asyncio
async def test_recently_used_server_not_disconnected():
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["exa"] = mock_session
    manager.always_on_servers = set()
    manager.idle_timeouts["exa"] = 300  # 5 minutes
    manager.last_used["exa"] = time.monotonic()  # just used

    await manager._disconnect_idle_servers()

    assert "exa" in manager.clients
