"""Tests for trigger manager fixes."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.asyncio
async def test_trigger_manager_does_not_swallow_unexpected_errors():
    """Trigger manager should not catch unexpected errors like SystemExit."""
    from src.multimcp.mcp_trigger_manager import MCPTriggerManager

    client_manager = MagicMock()
    mgr = MCPTriggerManager(client_manager)

    # Setup: one pending server with matching triggers
    client_manager.pending_configs = {"test-server": {"triggers": ["hello"]}}

    # get_or_create_client raises SystemExit (should NOT be caught)
    client_manager.get_or_create_client = AsyncMock(side_effect=SystemExit(1))

    with (
        patch(
            "src.multimcp.mcp_trigger_manager.extract_keywords_from_message",
            return_value="hello world",
        ),
        patch(
            "src.multimcp.mcp_trigger_manager.match_triggers",
            return_value=True,
        ),
    ):
        with pytest.raises(SystemExit):
            await mgr.check_and_enable({"content": "hello world"})


@pytest.mark.asyncio
async def test_trigger_manager_catches_connection_error():
    """Trigger manager should catch ConnectionError and log it."""
    from src.multimcp.mcp_trigger_manager import MCPTriggerManager

    client_manager = MagicMock()
    mgr = MCPTriggerManager(client_manager)

    client_manager.pending_configs = {"test-server": {"triggers": ["hello"]}}
    client_manager.get_or_create_client = AsyncMock(
        side_effect=ConnectionError("refused")
    )

    with (
        patch(
            "src.multimcp.mcp_trigger_manager.extract_keywords_from_message",
            return_value="hello world",
        ),
        patch(
            "src.multimcp.mcp_trigger_manager.match_triggers",
            return_value=True,
        ),
    ):
        result = await mgr.check_and_enable({"content": "hello world"})
        assert result == []  # Server NOT enabled due to connection failure


@pytest.mark.asyncio
async def test_trigger_manager_catches_timeout_error():
    """Trigger manager should catch TimeoutError gracefully."""
    from src.multimcp.mcp_trigger_manager import MCPTriggerManager

    client_manager = MagicMock()
    mgr = MCPTriggerManager(client_manager)

    client_manager.pending_configs = {"test-server": {"triggers": ["hello"]}}
    client_manager.get_or_create_client = AsyncMock(
        side_effect=TimeoutError("timed out")
    )

    with (
        patch(
            "src.multimcp.mcp_trigger_manager.extract_keywords_from_message",
            return_value="hello world",
        ),
        patch(
            "src.multimcp.mcp_trigger_manager.match_triggers",
            return_value=True,
        ),
    ):
        result = await mgr.check_and_enable({"content": "hello world"})
        assert result == []


@pytest.mark.asyncio
async def test_trigger_manager_catches_key_error():
    """Trigger manager must catch KeyError from get_or_create_client.

    KeyError is raised when a server name is not found in pending_configs or
    clients (race condition: server removed between iteration snapshot and connect).
    The old specific except clause missed KeyError, causing the trigger to crash.
    """
    from src.multimcp.mcp_trigger_manager import MCPTriggerManager

    client_manager = MagicMock()
    mgr = MCPTriggerManager(client_manager)

    client_manager.pending_configs = {"test-server": {"triggers": ["hello"]}}
    client_manager.get_or_create_client = AsyncMock(
        side_effect=KeyError("test-server")
    )

    with (
        patch(
            "src.multimcp.mcp_trigger_manager.extract_keywords_from_message",
            return_value="hello world",
        ),
        patch(
            "src.multimcp.mcp_trigger_manager.match_triggers",
            return_value=True,
        ),
    ):
        result = await mgr.check_and_enable({"content": "hello world"})
        assert result == []  # Must not raise, must return empty list
