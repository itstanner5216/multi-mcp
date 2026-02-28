import pytest
from mcp import types
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry
from src.multimcp.cache_manager import merge_discovered_tools, get_enabled_tools, cleanup_stale_tools

def _make_tool(name: str, description: str = "", input_schema: dict | None = None) -> types.Tool:
    schema = input_schema if input_schema is not None else {"type": "object", "properties": {}}
    return types.Tool(name=name, description=description, inputSchema=schema)

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


# ---------------------------------------------------------------------------
# inputSchema persistence — the core fix
# ---------------------------------------------------------------------------

def test_merge_persists_input_schema_for_new_tool():
    """merge_discovered_tools must store inputSchema on new tool entries."""
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    }
    config = MultiMCPConfig(servers={"exa": ServerConfig()})
    tool = _make_tool("web_search", "Search the web", input_schema=schema)
    merge_discovered_tools(config, "exa", [tool])

    entry = config.servers["exa"].tools["web_search"]
    assert entry.input_schema == schema, "inputSchema must be persisted to ToolEntry"


def test_merge_updates_input_schema_on_existing_tool():
    """merge_discovered_tools must update inputSchema when a tool already exists."""
    old_schema = {"type": "object", "properties": {}}
    new_schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}

    config = MultiMCPConfig(servers={
        "exa": ServerConfig(tools={"web_search": ToolEntry(input_schema=old_schema)})
    })
    tool = _make_tool("web_search", "Search", input_schema=new_schema)
    merge_discovered_tools(config, "exa", [tool])

    assert config.servers["exa"].tools["web_search"].input_schema == new_schema


def test_merge_input_schema_none_when_tool_has_no_schema():
    """When tool has no inputSchema (None), entry.input_schema stays None."""
    config = MultiMCPConfig(servers={"srv": ServerConfig()})
    tool = types.Tool(name="bare_tool", description="", inputSchema={})
    merge_discovered_tools(config, "srv", [tool])

    # Empty dict inputSchema is stored as-is (not converted to None)
    entry = config.servers["srv"].tools["bare_tool"]
    assert entry.input_schema == {}


def test_tool_entry_input_schema_roundtrips_yaml(tmp_path):
    """ToolEntry.input_schema must survive YAML save/load roundtrip."""
    from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry, save_config, load_config
    from pathlib import Path

    schema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    }
    config = MultiMCPConfig(servers={
        "weather": ServerConfig(tools={
            "get_weather": ToolEntry(
                enabled=True,
                description="Get weather",
                input_schema=schema,
            )
        })
    })
    path = tmp_path / "servers.yaml"
    save_config(config, path)
    reloaded = load_config(path)

    tool_entry = reloaded.servers["weather"].tools["get_weather"]
    assert tool_entry.input_schema == schema


def test_load_tools_from_yaml_uses_cached_schema():
    """load_tools_from_yaml must use cached inputSchema instead of empty default."""
    from unittest.mock import MagicMock
    from src.multimcp.mcp_proxy import MCPProxyServer
    from src.multimcp.mcp_client import MCPClientManager
    from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry

    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    yaml_config = MultiMCPConfig(servers={
        "exa": ServerConfig(tools={
            "web_search": ToolEntry(
                enabled=True,
                description="Search",
                input_schema=schema,
            )
        })
    })

    client_manager = MCPClientManager()
    proxy = MCPProxyServer(client_manager)
    proxy.load_tools_from_yaml(yaml_config)

    tool_mapping = proxy.tool_to_server.get("exa__web_search")
    assert tool_mapping is not None
    assert tool_mapping.tool.inputSchema == schema, (
        "Cached tool must use stored inputSchema, not empty default"
    )


def test_load_tools_from_yaml_falls_back_when_no_cached_schema():
    """load_tools_from_yaml must use empty default when input_schema is None."""
    from src.multimcp.mcp_proxy import MCPProxyServer
    from src.multimcp.mcp_client import MCPClientManager
    from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry

    yaml_config = MultiMCPConfig(servers={
        "old_server": ServerConfig(tools={
            "legacy_tool": ToolEntry(
                enabled=True,
                description="Legacy",
                input_schema=None,  # No schema cached (older YAML format)
            )
        })
    })

    client_manager = MCPClientManager()
    proxy = MCPProxyServer(client_manager)
    proxy.load_tools_from_yaml(yaml_config)

    tool_mapping = proxy.tool_to_server.get("old_server__legacy_tool")
    assert tool_mapping is not None
    assert tool_mapping.tool.inputSchema == {"type": "object", "properties": {}}, (
        "Must fall back to empty schema when none cached"
    )
