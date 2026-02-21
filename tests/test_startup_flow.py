import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry, save_config
from src.multimcp.mcp_client import MCPClientManager


@pytest.mark.asyncio
async def test_bootstrap_applies_tool_filters_from_yaml(tmp_path):
    """Tools marked enabled=False in YAML are excluded from client_manager.tool_filters."""
    from src.multimcp.multi_mcp import MultiMCP

    yaml_path = tmp_path / "servers.yaml"
    config = MultiMCPConfig(servers={
        "github": ServerConfig(
            command="/fake/run-github.sh",
            always_on=True,
            idle_timeout_minutes=5,
            tools={
                "search_repositories": ToolEntry(enabled=True),
                "delete_repository": ToolEntry(enabled=False),
            }
        )
    })
    save_config(config, yaml_path)

    server = MultiMCP(transport="stdio", config="./examples/config/mcp.json")

    # Patch discover_all so we don't actually connect
    server.client_manager.discover_all = AsyncMock(return_value={})

    await server._bootstrap_from_yaml(yaml_path)

    # Only enabled tools should be in the allow list
    assert "github" in server.client_manager.tool_filters
    allow_list = server.client_manager.tool_filters["github"]["allow"]
    assert "search_repositories" in allow_list
    assert "delete_repository" not in allow_list


@pytest.mark.asyncio
async def test_bootstrap_sets_always_on_and_idle_timeout(tmp_path):
    """always_on=True servers added to always_on_servers, idle_timeout set correctly."""
    from src.multimcp.multi_mcp import MultiMCP

    yaml_path = tmp_path / "servers.yaml"
    config = MultiMCPConfig(servers={
        "github": ServerConfig(command="/fake/run-github.sh", always_on=True, idle_timeout_minutes=10),
        "exa": ServerConfig(url="https://mcp.exa.ai", always_on=False, idle_timeout_minutes=3),
    })
    save_config(config, yaml_path)

    server = MultiMCP(transport="stdio", config="./examples/config/mcp.json")
    server.client_manager.discover_all = AsyncMock(return_value={})

    await server._bootstrap_from_yaml(yaml_path)

    assert "github" in server.client_manager.always_on_servers
    assert "exa" not in server.client_manager.always_on_servers
    assert server.client_manager.idle_timeouts["github"] == 600  # 10 * 60
    assert server.client_manager.idle_timeouts["exa"] == 180    # 3 * 60


@pytest.mark.asyncio
async def test_first_run_discovery_writes_yaml(tmp_path):
    """When no YAML exists, _first_run_discovery runs and writes the YAML file."""
    from src.multimcp.multi_mcp import MultiMCP
    from unittest.mock import AsyncMock, MagicMock, patch
    from mcp import types

    yaml_path = tmp_path / "servers.yaml"
    assert not yaml_path.exists()

    server = MultiMCP(transport="stdio", config="./examples/config/mcp.json")

    mock_tool = MagicMock(spec=types.Tool)
    mock_tool.name = "web_search_exa"
    mock_tool.description = "Search the web"

    # Mock discover_all to return a tool for one server
    server.client_manager.discover_all = AsyncMock(
        return_value={"exa": [mock_tool]}
    )

    # Patch load_mcp_config to return a config with one server
    with patch.object(server, "load_mcp_config", return_value={
        "mcpServers": {
            "exa": {"url": "https://mcp.exa.ai/mcp", "always_on": False}
        }
    }):
        config = await server._first_run_discovery(yaml_path)

    # YAML file was written
    assert yaml_path.exists()
    # Discovered tool is in config
    assert "exa" in config.servers
    assert "web_search_exa" in config.servers["exa"].tools
    assert config.servers["exa"].tools["web_search_exa"].enabled is True
