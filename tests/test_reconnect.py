import pytest
import time
from unittest.mock import AsyncMock
from src.multimcp.mcp_client import MCPClientManager

@pytest.mark.asyncio
async def test_get_or_create_records_usage_on_existing_client():
    """get_or_create_client records last_used timestamp when returning existing client."""
    manager = MCPClientManager()
    mock_session = AsyncMock()
    manager.clients["exa"] = mock_session

    before = time.monotonic()
    client = await manager.get_or_create_client("exa")
    after = time.monotonic()

    assert before <= manager.last_used["exa"] <= after
    assert client is mock_session

@pytest.mark.asyncio
async def test_get_or_create_records_usage_on_new_client():
    """get_or_create_client records last_used timestamp when creating from pending config."""
    manager = MCPClientManager()
    mock_session = AsyncMock()

    # Add a pending config
    manager.pending_configs["tavily"] = {"command": "/fake/run-tavily.sh"}

    # Mock _create_single_client to just add the client
    async def fake_create(name, config):
        manager.clients[name] = mock_session
    manager._create_single_client = fake_create

    before = time.monotonic()
    client = await manager.get_or_create_client("tavily")
    after = time.monotonic()

    assert before <= manager.last_used["tavily"] <= after
    assert client is mock_session
