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
