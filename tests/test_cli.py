import pytest
from pathlib import Path
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry, save_config
from src.multimcp.cli import cmd_list, cmd_status

def test_cmd_list_shows_enabled_and_disabled(tmp_path):
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={
            "search_repositories": ToolEntry(enabled=True),
            "delete_repository": ToolEntry(enabled=False),
            "old_tool": ToolEntry(enabled=True, stale=True),
        })
    })
    path = tmp_path / "servers.yaml"
    save_config(config, path)

    output = cmd_list(yaml_path=path)
    assert "search_repositories" in output
    assert "delete_repository" in output
    assert "✓" in output
    assert "✗" in output
    assert "stale" in output.lower()

def test_cmd_status_shows_server_counts(tmp_path):
    config = MultiMCPConfig(servers={
        "github": ServerConfig(always_on=True, tools={"t1": ToolEntry()}),
        "exa": ServerConfig(always_on=False, tools={"t2": ToolEntry(), "t3": ToolEntry(enabled=False)}),
    })
    path = tmp_path / "servers.yaml"
    save_config(config, path)

    output = cmd_status(yaml_path=path)
    assert "github" in output
    assert "exa" in output
    assert "always_on" in output.lower() or "always" in output.lower()

def test_cmd_list_no_servers(tmp_path):
    path = tmp_path / "nonexistent.yaml"
    output = cmd_list(yaml_path=path)
    assert "no servers" in output.lower() or "not configured" in output.lower()


@pytest.mark.asyncio
async def test_cmd_refresh_updates_yaml(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch
    from mcp import types
    from src.multimcp.cli import cmd_refresh

    # Set up initial YAML with one server
    config = MultiMCPConfig(servers={
        "exa": ServerConfig(url="https://mcp.exa.ai/mcp", always_on=False)
    })
    path = tmp_path / "servers.yaml"
    save_config(config, path)

    mock_tool = MagicMock(spec=types.Tool)
    mock_tool.name = "web_search_exa"
    mock_tool.description = "Search the web"

    with patch("src.multimcp.mcp_client.MCPClientManager") as MockManager:
        mock_manager = AsyncMock()
        MockManager.return_value = mock_manager
        mock_manager.discover_all = AsyncMock(return_value={"exa": [mock_tool]})

        result = await cmd_refresh(yaml_path=path)

    assert "✅" in result
    # Tool should now be in YAML
    from src.multimcp.yaml_config import load_config
    updated = load_config(path)
    assert "web_search_exa" in updated.servers["exa"].tools
