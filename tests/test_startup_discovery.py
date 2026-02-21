import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig

@pytest.mark.asyncio
async def test_discover_all_returns_tool_dict():
    """discover_all connects, fetches tools, returns {server: [tools]}."""
    manager = MCPClientManager()

    mock_tool = MagicMock()
    mock_tool.name = "search_repositories"
    mock_tool.description = "Search repos"

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[mock_tool]))

    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=False)
    })

    with patch.object(manager, "_create_single_client", new_callable=AsyncMock) as mock_create:
        async def fake_create(name, server_config):
            manager.clients[name] = mock_session
        mock_create.side_effect = fake_create

        results = await manager.discover_all(config)

    assert "github" in results
    assert results["github"][0].name == "search_repositories"

@pytest.mark.asyncio
async def test_discover_all_disconnects_lazy_servers():
    """After discovery, lazy servers are removed from clients dict."""
    manager = MCPClientManager()

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    config = MultiMCPConfig(servers={
        "tavily": ServerConfig(command="/fake/run-tavily.sh", always_on=False)
    })

    with patch.object(manager, "_create_single_client", new_callable=AsyncMock) as mock_create:
        async def fake_create(name, server_config):
            manager.clients[name] = mock_session
        mock_create.side_effect = fake_create

        await manager.discover_all(config)

    assert "tavily" not in manager.clients

@pytest.mark.asyncio
async def test_discover_all_keeps_always_on_connected():
    """After discovery, always_on servers remain in clients dict."""
    manager = MCPClientManager()

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=MagicMock(
        capabilities=MagicMock(tools=True, prompts=False, resources=False)
    ))
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=True)
    })

    with patch.object(manager, "_create_single_client", new_callable=AsyncMock) as mock_create:
        async def fake_create(name, server_config):
            manager.clients[name] = mock_session
        mock_create.side_effect = fake_create

        await manager.discover_all(config)

    assert "github" in manager.clients
