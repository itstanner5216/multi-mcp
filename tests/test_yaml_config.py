import pytest
import yaml
import tempfile
from pathlib import Path
from src.multimcp.yaml_config import ToolEntry, ServerConfig, MultiMCPConfig, load_config, save_config

def test_tool_entry_defaults():
    t = ToolEntry()
    assert t.enabled is True
    assert t.stale is False
    assert t.description == ""

def test_server_config_defaults():
    s = ServerConfig()
    assert s.always_on is False
    assert s.idle_timeout_minutes == 5
    assert s.tools == {}

def test_load_config_from_yaml():
    content = """
servers:
  github:
    command: /usr/bin/run-github.sh
    always_on: true
    tools:
      search_repositories:
        enabled: true
      create_gist:
        enabled: false
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = Path(f.name)

    config = load_config(path)
    assert "github" in config.servers
    assert config.servers["github"].always_on is True
    assert config.servers["github"].tools["search_repositories"].enabled is True
    assert config.servers["github"].tools["create_gist"].enabled is False

def test_save_and_reload_config():
    config = MultiMCPConfig(servers={
        "exa": ServerConfig(
            url="https://mcp.exa.ai/mcp",
            always_on=False,
            tools={"web_search_exa": ToolEntry(enabled=True, description="Search the web")}
        )
    })
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = Path(f.name)

    save_config(config, path)
    reloaded = load_config(path)
    assert reloaded.servers["exa"].tools["web_search_exa"].enabled is True
    assert reloaded.servers["exa"].tools["web_search_exa"].description == "Search the web"

def test_load_missing_file_returns_empty_config():
    config = load_config(Path("/tmp/does_not_exist_multi_mcp.yaml"))
    assert config.servers == {}
