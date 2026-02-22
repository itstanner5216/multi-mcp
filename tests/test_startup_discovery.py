import pytest
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig


def _make_mock_session(tools=None):
    """Build a mock ClientSession that works as an async context manager."""
    if tools is None:
        tools = []
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=tools))
    # Make the session itself usable as an async context manager
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def _make_mock_transport():
    """Build a mock read/write pair returned by stdio_client / sse_client."""
    mock_read = AsyncMock()
    mock_write = AsyncMock()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_read, mock_write

    return _ctx, mock_read, mock_write


@pytest.mark.asyncio
async def test_discover_all_returns_tool_dict():
    """discover_all connects, fetches tools, returns {server: [tools]}."""
    manager = MCPClientManager()

    mock_tool = MagicMock()
    mock_tool.name = "search_repositories"
    mock_tool.description = "Search repos"

    mock_session = _make_mock_session(tools=[mock_tool])
    transport_ctx, _, _ = _make_mock_transport()

    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=False)
    })

    with patch("src.multimcp.mcp_client.stdio_client", transport_ctx), \
         patch("src.multimcp.mcp_client.ClientSession", return_value=mock_session):
        results = await manager.discover_all(config)

    assert "github" in results
    assert results["github"][0].name == "search_repositories"


@pytest.mark.asyncio
async def test_discover_all_disconnects_lazy_servers():
    """After discovery, lazy servers are NOT kept in clients dict."""
    manager = MCPClientManager()

    mock_session = _make_mock_session(tools=[])
    transport_ctx, _, _ = _make_mock_transport()

    config = MultiMCPConfig(servers={
        "tavily": ServerConfig(command="/fake/run-tavily.sh", always_on=False)
    })

    with patch("src.multimcp.mcp_client.stdio_client", transport_ctx), \
         patch("src.multimcp.mcp_client.ClientSession", return_value=mock_session):
        await manager.discover_all(config)

    assert "tavily" not in manager.clients


@pytest.mark.asyncio
async def test_discover_all_keeps_always_on_connected():
    """After discovery, always_on servers remain in clients dict."""
    manager = MCPClientManager()

    mock_session = _make_mock_session(tools=[])
    transport_ctx, _, _ = _make_mock_transport()

    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=True)
    })

    with patch("src.multimcp.mcp_client.stdio_client", transport_ctx), \
         patch("src.multimcp.mcp_client.ClientSession", return_value=mock_session):
        await manager.discover_all(config)

    assert "github" in manager.clients


@pytest.mark.asyncio
async def test_discover_all_handles_failed_server_gracefully():
    """If a server fails during discovery, result for that server is empty list."""
    manager = MCPClientManager()

    config = MultiMCPConfig(servers={
        "broken_server": ServerConfig(command="/nonexistent/command", always_on=False)
    })

    # Patch stdio_client to raise so the except branch in discover_all fires
    with patch("src.multimcp.mcp_client.stdio_client", side_effect=Exception("spawn failed")):
        results = await manager.discover_all(config)

    assert "broken_server" in results
    assert results["broken_server"] == []
