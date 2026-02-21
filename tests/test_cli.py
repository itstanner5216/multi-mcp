import pytest
import tempfile
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
