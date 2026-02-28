import pytest
import yaml
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

def test_load_config_from_yaml(tmp_path):
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
    path = tmp_path / "config.yaml"
    path.write_text(content)
    config = load_config(path)
    assert "github" in config.servers
    assert config.servers["github"].always_on is True
    assert config.servers["github"].tools["search_repositories"].enabled is True
    assert config.servers["github"].tools["create_gist"].enabled is False

def test_save_and_reload_config(tmp_path):
    config = MultiMCPConfig(servers={
        "exa": ServerConfig(
            url="https://mcp.exa.ai/mcp",
            always_on=False,
            tools={"web_search_exa": ToolEntry(enabled=True, description="Search the web")}
        )
    })
    path = tmp_path / "config.yaml"
    save_config(config, path)
    reloaded = load_config(path)
    assert reloaded.servers["exa"].tools["web_search_exa"].enabled is True
    assert reloaded.servers["exa"].tools["web_search_exa"].description == "Search the web"

def test_load_missing_file_returns_empty_config():
    config = load_config(Path("/tmp/does_not_exist_multi_mcp.yaml"))
    assert config.servers == {}


def test_save_config_raises_on_write_error(tmp_path):
    """save_config must raise OSError (not swallow it) when file cannot be written.

    Callers should catch OSError to avoid crashing startup on disk/perms failures.
    """
    from unittest.mock import patch, mock_open
    import builtins

    config = MultiMCPConfig()
    path = tmp_path / "config.yaml"

    original_open = builtins.open
    def _raise_on_write(file, mode="r", *args, **kwargs):
        if "w" in str(mode):
            raise OSError("disk full")
        return original_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=_raise_on_write):
        with pytest.raises(OSError, match="disk full"):
            save_config(config, path)


def test_save_config_logs_and_raises_on_mkdir_error(tmp_path):
    """save_config must raise OSError when the parent directory cannot be created."""
    from unittest.mock import patch
    from pathlib import Path

    config = MultiMCPConfig()
    # Use a path under a non-existent root that can't be created
    path = tmp_path / "config.yaml"

    with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
        with pytest.raises(OSError, match="permission denied"):
            save_config(config, path)
