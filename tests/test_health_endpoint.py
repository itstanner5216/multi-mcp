"""
Tests for /health endpoint
Following TDD: RED → GREEN → REFACTOR
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.multimcp.multi_mcp import MultiMCP
from src.multimcp.mcp_proxy import MCPProxyServer
from src.multimcp.mcp_client import MCPClientManager


@pytest.fixture
def multi_mcp():
    """Create a MultiMCP instance for testing."""
    return MultiMCP(transport="sse")


@pytest.fixture
def mock_proxy_with_clients():
    """Create a mock proxy with 2 connected clients."""
    proxy = MagicMock(spec=MCPProxyServer)
    client_manager = MagicMock(spec=MCPClientManager)
    client_manager.clients = {"server1": MagicMock(), "server2": MagicMock()}
    client_manager.pending_configs = {}
    proxy.client_manager = client_manager
    return proxy


@pytest.fixture
def mock_proxy_with_pending():
    """Create a mock proxy with 1 connected and 2 pending clients (for Task 05)."""
    proxy = MagicMock(spec=MCPProxyServer)
    client_manager = MagicMock(spec=MCPClientManager)
    client_manager.clients = {"server1": MagicMock()}
    # Task 05 will add pending_configs
    client_manager.pending_configs = {"server2": {}, "server3": {}}
    proxy.client_manager = client_manager
    return proxy


@pytest.mark.asyncio
async def test_health_endpoint_returns_connected_count(
    multi_mcp, mock_proxy_with_clients
):
    """Test that /health returns correct count of connected servers."""
    multi_mcp.proxy = mock_proxy_with_clients

    # Create a mock request
    request = MagicMock(spec=Request)

    response = await multi_mcp.handle_health(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200

    # Parse the response body
    import json

    body = json.loads(response.body.decode())

    assert body["status"] == "healthy"
    assert body["connected_servers"] == 2
    assert body["pending_servers"] == 0


@pytest.mark.asyncio
async def test_health_endpoint_with_pending_servers(multi_mcp, mock_proxy_with_pending):
    """Test that /health counts pending_configs when it exists (Task 05)."""
    multi_mcp.proxy = mock_proxy_with_pending

    request = MagicMock(spec=Request)

    response = await multi_mcp.handle_health(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200

    import json

    body = json.loads(response.body.decode())

    assert body["status"] == "healthy"
    assert body["connected_servers"] == 1
    assert body["pending_servers"] == 2


@pytest.mark.asyncio
async def test_health_endpoint_no_proxy_initialized(multi_mcp):
    """Test that /health handles case when proxy is not yet initialized."""
    multi_mcp.proxy = None

    request = MagicMock(spec=Request)

    response = await multi_mcp.handle_health(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503  # Service Unavailable

    import json

    body = json.loads(response.body.decode())

    assert body["status"] == "unavailable"
    assert "error" in body


@pytest.mark.asyncio
async def test_health_endpoint_zero_servers(multi_mcp):
    """Test that /health handles case with zero connected servers."""
    proxy = MagicMock(spec=MCPProxyServer)
    client_manager = MagicMock(spec=MCPClientManager)
    client_manager.clients = {}  # No clients
    client_manager.pending_configs = {}
    proxy.client_manager = client_manager
    multi_mcp.proxy = proxy

    request = MagicMock(spec=Request)

    response = await multi_mcp.handle_health(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200

    import json

    body = json.loads(response.body.decode())

    assert body["status"] == "healthy"
    assert body["connected_servers"] == 0
    assert body["pending_servers"] == 0
