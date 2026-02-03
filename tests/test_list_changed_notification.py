"""Tests for tools/list_changed notification emission."""

import pytest
from unittest.mock import AsyncMock, MagicMock, call
from mcp import types
from mcp.client.session import ClientSession
from src.multimcp.mcp_proxy import MCPProxyServer
from src.multimcp.mcp_client import MCPClientManager


@pytest.fixture
def mock_client_manager():
    """Create a mock client manager with empty clients."""
    manager = MCPClientManager()
    manager.clients = {}
    return manager


@pytest.fixture
def proxy_server(mock_client_manager):
    """Create a proxy server with mock client manager."""
    proxy = MCPProxyServer(mock_client_manager)
    return proxy


@pytest.mark.asyncio
async def test_register_client_sends_list_changed_notification(
    proxy_server, mock_client_manager
):
    """Test that registering a new client triggers tools/list_changed notification."""
    # RED: This test should fail because notification isn't implemented yet

    # Create a mock client with tools capability
    mock_client = AsyncMock(spec=ClientSession)
    mock_client.initialize.return_value = types.InitializeResult(
        protocolVersion="1.0",
        capabilities=types.ServerCapabilities(tools=types.ToolsCapability()),
        serverInfo=types.Implementation(name="test", version="1.0"),
    )

    # Mock list_tools to return a tool
    mock_tool = types.Tool(name="test_tool", description="A test tool", inputSchema={})
    mock_client.list_tools.return_value = types.ListToolsResult(tools=[mock_tool])

    # Track if notification was sent
    notification_sent = False

    async def mock_send_notification():
        nonlocal notification_sent
        notification_sent = True

    # Mock the _send_tools_list_changed method
    proxy_server._send_tools_list_changed = mock_send_notification

    # Register the client
    await proxy_server.register_client("test_server", mock_client)

    # Assert notification was sent
    assert notification_sent, (
        "tools/list_changed notification should be sent after registering a client"
    )


@pytest.mark.asyncio
async def test_unregister_client_sends_list_changed_notification(
    proxy_server, mock_client_manager
):
    """Test that unregistering a client triggers tools/list_changed notification."""
    # RED: This test should fail because notification isn't implemented yet

    # First, add a client
    mock_client = AsyncMock(spec=ClientSession)
    mock_client.initialize.return_value = types.InitializeResult(
        protocolVersion="1.0",
        capabilities=types.ServerCapabilities(tools=types.ToolsCapability()),
        serverInfo=types.Implementation(name="test", version="1.0"),
    )

    mock_tool = types.Tool(name="test_tool", description="A test tool", inputSchema={})
    mock_client.list_tools.return_value = types.ListToolsResult(tools=[mock_tool])

    await proxy_server.register_client("test_server", mock_client)

    # Track if notification was sent
    notification_sent = False

    async def mock_send_notification():
        nonlocal notification_sent
        notification_sent = True

    # Mock the _send_tools_list_changed method
    proxy_server._send_tools_list_changed = mock_send_notification

    # Unregister the client
    await proxy_server.unregister_client("test_server")

    # Assert notification was sent
    assert notification_sent, (
        "tools/list_changed notification should be sent after unregistering a client"
    )


@pytest.mark.asyncio
async def test_notification_not_sent_for_servers_without_tools(
    proxy_server, mock_client_manager
):
    """Test that notification is only sent when tools capability changes."""
    # RED: This test should fail initially

    # Create a mock client WITHOUT tools capability (prompts only)
    mock_client = AsyncMock(spec=ClientSession)
    mock_client.initialize.return_value = types.InitializeResult(
        protocolVersion="1.0",
        capabilities=types.ServerCapabilities(prompts=types.PromptsCapability()),
        serverInfo=types.Implementation(name="test", version="1.0"),
    )

    # Track if notification was sent
    notification_sent = False

    async def mock_send_notification():
        nonlocal notification_sent
        notification_sent = True

    # Mock the _send_tools_list_changed method
    proxy_server._send_tools_list_changed = mock_send_notification

    # Register the client
    await proxy_server.register_client("prompts_only_server", mock_client)

    # Assert notification was NOT sent (no tools capability)
    assert not notification_sent, (
        "tools/list_changed notification should NOT be sent for servers without tools capability"
    )
