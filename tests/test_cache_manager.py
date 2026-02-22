import pytest
from mcp import types
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry
from src.multimcp.cache_manager import merge_discovered_tools, get_enabled_tools, cleanup_stale_tools

def _make_tool(name: str, description: str = "") -> types.Tool:
    return types.Tool(name=name, description=description, inputSchema={"type": "object", "properties": {}})

def test_new_tools_added_as_enabled():
    config = MultiMCPConfig(servers={"github": ServerConfig()})
    discovered = [_make_tool("search_repositories", "Search repos")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["search_repositories"].enabled is True
    assert result.servers["github"].tools["search_repositories"].stale is False

def test_user_disabled_tool_preserved():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"create_gist": ToolEntry(enabled=False)})
    })
    discovered = [_make_tool("create_gist")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["create_gist"].enabled is False

def test_gone_tool_marked_stale():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"old_tool": ToolEntry(enabled=True)})
    })
    discovered = [_make_tool("new_tool")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["old_tool"].stale is True
    assert result.servers["github"].tools["old_tool"].enabled is True

def test_returned_tool_clears_stale():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"search_repositories": ToolEntry(enabled=True, stale=True)})
    })
    discovered = [_make_tool("search_repositories")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["search_repositories"].stale is False

def test_description_updated_on_refresh():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={"search_repositories": ToolEntry(description="old")})
    })
    discovered = [_make_tool("search_repositories", "new description")]
    result = merge_discovered_tools(config, "github", discovered)
    assert result.servers["github"].tools["search_repositories"].description == "new description"
    assert result.servers["github"].tools["search_repositories"].enabled is True

def test_get_enabled_tools_filters_disabled_and_stale():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={
            "good": ToolEntry(enabled=True, stale=False),
            "disabled": ToolEntry(enabled=False),
            "stale": ToolEntry(enabled=True, stale=True),
        })
    })
    enabled = get_enabled_tools(config, "github")
    assert enabled == {"good"}


def test_cleanup_removes_stale_and_disabled():
    config = MultiMCPConfig(servers={
        "github": ServerConfig(tools={
            "old_tool": ToolEntry(enabled=False, stale=True),    # should be removed
            "active": ToolEntry(enabled=True, stale=False),      # keep
            "stale_but_on": ToolEntry(enabled=True, stale=True), # keep (user wants it)
            "off_not_stale": ToolEntry(enabled=False, stale=False), # keep (user disabled)
        })
    })
    removed = cleanup_stale_tools(config, "github")
    assert removed == 1
    assert "old_tool" not in config.servers["github"].tools
    assert "active" in config.servers["github"].tools
    assert "stale_but_on" in config.servers["github"].tools
    assert "off_not_stale" in config.servers["github"].tools
