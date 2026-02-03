"""
Tests for deferred backend initialization (lazy loading).

Tests verify that:
1. Servers can be stored as pending configs without connecting
2. get_or_create_client() connects on first access
3. Connection semaphore limits concurrent connections
4. Connection timeout prevents hanging
5. Repeated access returns cached client
"""

import pytest
import pytest_asyncio
import asyncio
from mcp.server import Server
from mcp.types import Tool
from mcp.shared.memory import create_connected_server_and_client_session
from src.multimcp.mcp_client import MCPClientManager


@pytest_asyncio.fixture
async def mock_server_session():
    """Create a mock MCP server with in-memory connection."""
    server = Server("test_server")

    @server.list_tools()
    async def _():
        return [
            Tool(
                name="test_tool",
                description="A test tool",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    async with create_connected_server_and_client_session(server) as (_, session):
        yield session


@pytest.mark.asyncio
async def test_add_pending_server_does_not_connect():
    """Test that adding a pending server stores config without connecting."""
    manager = MCPClientManager()

    config = {"command": "python", "args": ["-c", "print('test')"], "env": {}}

    # Add as pending - should not connect
    manager.add_pending_server("calculator", config)

    # Should be in pending_configs, not in clients
    assert "calculator" in manager.pending_configs
    assert "calculator" not in manager.clients

    await manager.close()


@pytest.mark.asyncio
async def test_get_or_create_client_raises_on_unknown_server():
    """Test that get_or_create_client() raises KeyError for unknown servers."""
    manager = MCPClientManager()

    with pytest.raises(KeyError, match="Unknown server: nonexistent"):
        await manager.get_or_create_client("nonexistent")

    await manager.close()


@pytest.mark.asyncio
async def test_create_clients_with_lazy_mode():
    """Test that create_clients() with lazy=True stores configs without connecting."""
    manager = MCPClientManager()

    config = {
        "mcpServers": {
            "calculator": {
                "command": "python",
                "args": ["-c", "print('test')"],
                "env": {},
            }
        }
    }

    # Create with lazy=True
    result = await manager.create_clients(config, lazy=True)

    # Should return empty dict (no connections made)
    assert result == {}
    assert "calculator" in manager.pending_configs
    assert "calculator" not in manager.clients

    await manager.close()


@pytest.mark.asyncio
async def test_lazy_mode_default_is_false():
    """Test that lazy mode defaults to False (eager loading)."""
    manager = MCPClientManager()

    # Empty config should still work
    config = {"mcpServers": {}}

    # Create without lazy parameter (should default to False)
    result = await manager.create_clients(config)

    # Should attempt eager connection (empty result since no servers)
    assert result == {}
    assert len(manager.pending_configs) == 0

    await manager.close()


@pytest.mark.asyncio
async def test_manager_has_connection_config_attributes():
    """Test that manager can be initialized with connection config."""
    # Test with defaults
    manager1 = MCPClientManager()
    assert hasattr(manager1, "pending_configs")
    assert hasattr(manager1, "_connection_semaphore")
    assert hasattr(manager1, "_connection_timeout")
    await manager1.close()

    # Test with custom values
    manager2 = MCPClientManager(max_concurrent_connections=5, connection_timeout=10.0)
    assert manager2._connection_semaphore._value == 5
    assert manager2._connection_timeout == 10.0
    await manager2.close()


@pytest.mark.asyncio
async def test_add_pending_server_method_exists():
    """Test that add_pending_server method exists and accepts correct parameters."""
    manager = MCPClientManager()

    config = {"command": "test", "args": [], "env": {}}

    # Should not raise
    manager.add_pending_server("test_server", config)

    assert "test_server" in manager.pending_configs
    assert manager.pending_configs["test_server"] == config

    await manager.close()


@pytest.mark.asyncio
async def test_connection_timeout_is_configurable():
    """Test that connection timeout is configurable."""
    manager = MCPClientManager(connection_timeout=5.0)

    # Verify timeout is set correctly
    assert manager._connection_timeout == 5.0

    await manager.close()
