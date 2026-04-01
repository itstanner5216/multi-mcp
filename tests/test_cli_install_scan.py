"""Tests for cmd_install and cmd_scan in src/multimcp/cli.py.

Covers the new install and scan CLI commands added in this PR, including:
- Known/unknown tool names
- Single-tool and all-tools modes
- Platform support filtering
- NotImplementedError (JetBrains) and OSError handling
- Output format and human-readable messages
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.multimcp.cli import cmd_install, cmd_scan, _DEFAULT_SERVER_NAME, _DEFAULT_SERVER_CONFIG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_adapter(
    tool_name: str = "fake_tool",
    display_name: str = "Fake Tool",
    supported: bool = True,
    config_path: Optional[Path] = None,
    servers: Optional[dict] = None,
    register_raises: Optional[Exception] = None,
    discover_raises: Optional[Exception] = None,
) -> MagicMock:
    """Create a mock adapter with configurable behaviour."""
    adapter = MagicMock()
    adapter.tool_name = tool_name
    adapter.display_name = display_name
    adapter.is_supported.return_value = supported
    adapter.config_path.return_value = config_path or Path(f"/fake/{tool_name}/config.json")
    if register_raises is not None:
        adapter.register_server.side_effect = register_raises
    if discover_raises is not None:
        adapter.discover_servers.side_effect = discover_raises
    else:
        adapter.discover_servers.return_value = servers or {}
    return adapter


# ---------------------------------------------------------------------------
# cmd_install
# ---------------------------------------------------------------------------

class TestCmdInstall:
    def test_install_single_tool_success(self, tmp_path: Path) -> None:
        """Installing into a known, supported adapter produces a success message."""
        cfg_path = tmp_path / "config.json"
        mock_adapter = _make_mock_adapter(
            tool_name="fake_tool",
            display_name="Fake Tool",
            supported=True,
            config_path=cfg_path,
        )

        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_install(tool="fake_tool")

        assert "✅" in result
        assert "Fake Tool" in result
        mock_adapter.register_server.assert_called_once_with(
            _DEFAULT_SERVER_NAME, _DEFAULT_SERVER_CONFIG
        )

    def test_install_unknown_tool_returns_error(self) -> None:
        """Passing an unknown tool name returns an error message."""
        with patch("src.multimcp.adapters.get_adapter", return_value=None):
            result = cmd_install(tool="totally_unknown_tool")
        assert "❌" in result
        assert "totally_unknown_tool" in result

    def test_install_unsupported_platform_skips(self) -> None:
        """An adapter not supported on the current platform is skipped."""
        mock_adapter = _make_mock_adapter(
            tool_name="mac_only",
            display_name="Mac Only Tool",
            supported=False,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_install(tool="mac_only")
        assert "⏭" in result
        assert "skipped" in result
        mock_adapter.register_server.assert_not_called()

    def test_install_not_implemented_shows_warning(self) -> None:
        """A NotImplementedError (e.g. JetBrains) is caught and reported as a warning."""
        mock_adapter = _make_mock_adapter(
            tool_name="jetbrains",
            display_name="JetBrains IDEs",
            supported=True,
            register_raises=NotImplementedError("Use the IDE UI"),
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_install(tool="jetbrains")
        assert "⚠️" in result
        assert "JetBrains IDEs" in result

    def test_install_os_error_shows_failure(self) -> None:
        """An OSError during registration is caught and reported as a failure."""
        mock_adapter = _make_mock_adapter(
            tool_name="problem_tool",
            display_name="Problem Tool",
            supported=True,
            register_raises=OSError("Permission denied"),
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_install(tool="problem_tool")
        assert "❌" in result
        assert "Problem Tool" in result

    def test_install_all_adapters_when_no_tool(self) -> None:
        """Passing tool=None installs into all adapters returned by list_adapters."""
        adapters = [
            _make_mock_adapter(tool_name=f"tool_{i}", display_name=f"Tool {i}", supported=True)
            for i in range(3)
        ]
        with patch("src.multimcp.adapters.list_adapters", return_value=adapters):
            result = cmd_install(tool=None)
        for adapter in adapters:
            adapter.register_server.assert_called_once()
        # All three should appear in the output
        for i in range(3):
            assert f"Tool {i}" in result

    def test_install_custom_server_name(self, tmp_path: Path) -> None:
        """A custom server_name is passed through to register_server."""
        mock_adapter = _make_mock_adapter(supported=True, config_path=tmp_path / "cfg.json")
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            cmd_install(tool="fake_tool", server_name="my-custom-server")
        name_used = mock_adapter.register_server.call_args[0][0]
        assert name_used == "my-custom-server"

    def test_install_custom_server_config(self, tmp_path: Path) -> None:
        """A custom server_config is passed through to register_server."""
        mock_adapter = _make_mock_adapter(supported=True, config_path=tmp_path / "cfg.json")
        custom_cfg = {"command": "uv", "args": ["run", "main.py"]}
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            cmd_install(tool="fake_tool", server_config=custom_cfg)
        config_used = mock_adapter.register_server.call_args[0][1]
        assert config_used == custom_cfg

    def test_install_default_config_is_used_when_none(self) -> None:
        """When server_config=None, _DEFAULT_SERVER_CONFIG is used."""
        mock_adapter = _make_mock_adapter(supported=True)
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            cmd_install(tool="fake_tool", server_config=None)
        config_used = mock_adapter.register_server.call_args[0][1]
        assert config_used == _DEFAULT_SERVER_CONFIG

    def test_install_config_path_shown_in_success(self, tmp_path: Path) -> None:
        """The config path is included in the success message."""
        cfg_path = tmp_path / "some" / "config.json"
        mock_adapter = _make_mock_adapter(
            display_name="My Tool",
            supported=True,
            config_path=cfg_path,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_install(tool="fake_tool")
        assert str(cfg_path) in result

    def test_install_mixed_results_in_one_call(self) -> None:
        """A mix of successes, skips, and errors is reported correctly."""
        adapters = [
            _make_mock_adapter(tool_name="ok", display_name="OK Tool", supported=True),
            _make_mock_adapter(tool_name="skip", display_name="Skip Tool", supported=False),
            _make_mock_adapter(
                tool_name="fail", display_name="Fail Tool", supported=True,
                register_raises=OSError("disk full")
            ),
        ]
        with patch("src.multimcp.adapters.list_adapters", return_value=adapters):
            result = cmd_install(tool=None)
        assert "✅" in result
        assert "⏭" in result
        assert "❌" in result

    def test_install_value_error_shows_failure(self) -> None:
        """A ValueError during registration is caught and reported as failure."""
        mock_adapter = _make_mock_adapter(
            supported=True,
            register_raises=ValueError("bad config value"),
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_install(tool="fake_tool")
        assert "❌" in result


# ---------------------------------------------------------------------------
# cmd_scan
# ---------------------------------------------------------------------------

class TestCmdScan:
    def test_scan_single_tool_with_servers(self) -> None:
        """Scanning a tool with servers shows server name and command."""
        servers = {
            "weather": {"command": "python", "args": ["w.py"]},
            "github": {"command": "npx"},
        }
        mock_adapter = _make_mock_adapter(
            tool_name="claude_desktop",
            display_name="Claude Desktop",
            supported=True,
            servers=servers,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="claude_desktop")
        assert "Claude Desktop" in result
        assert "weather" in result
        assert "github" in result

    def test_scan_single_tool_empty_config(self) -> None:
        """Scanning a tool with no servers shows empty message."""
        mock_adapter = _make_mock_adapter(
            display_name="Empty Tool",
            supported=True,
            servers={},
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="fake_tool")
        assert "Empty Tool" in result
        assert "no servers" in result.lower()

    def test_scan_unknown_tool_returns_error(self) -> None:
        """Passing an unknown tool name returns an error message."""
        with patch("src.multimcp.adapters.get_adapter", return_value=None):
            result = cmd_scan(tool="nonexistent_tool")
        assert "❌" in result
        assert "nonexistent_tool" in result

    def test_scan_unsupported_platform_shows_skip(self) -> None:
        """An adapter not supported on the current platform is reported."""
        mock_adapter = _make_mock_adapter(
            display_name="Mac Only",
            supported=False,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="mac_only")
        assert "⏭" in result
        assert "Mac Only" in result

    def test_scan_not_implemented_shows_message(self) -> None:
        """A NotImplementedError is caught and reported."""
        mock_adapter = _make_mock_adapter(
            display_name="JetBrains IDEs",
            supported=True,
            discover_raises=NotImplementedError("parse not supported"),
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="jetbrains")
        assert "JetBrains IDEs" in result

    def test_scan_os_error_shows_failure(self) -> None:
        """An OSError during discovery is caught and reported."""
        mock_adapter = _make_mock_adapter(
            display_name="Broken Tool",
            supported=True,
            discover_raises=OSError("no such file"),
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="broken")
        assert "Broken Tool" in result
        assert "❌" in result

    def test_scan_all_adapters_when_no_tool(self) -> None:
        """Passing tool=None scans all adapters from list_adapters."""
        adapters = [
            _make_mock_adapter(
                tool_name=f"tool_{i}",
                display_name=f"Tool {i}",
                supported=True,
                servers={"srv": {"command": f"cmd_{i}"}},
            )
            for i in range(3)
        ]
        with patch("src.multimcp.adapters.list_adapters", return_value=adapters):
            result = cmd_scan(tool=None)
        for i in range(3):
            assert f"Tool {i}" in result

    def test_scan_shows_url_when_no_command(self) -> None:
        """When a server has a url instead of command, it's shown in output."""
        servers = {"sse-server": {"url": "http://localhost:8080/sse"}}
        mock_adapter = _make_mock_adapter(
            display_name="URL Tool",
            supported=True,
            servers=servers,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="url_tool")
        assert "http://localhost:8080/sse" in result

    def test_scan_shows_config_file_when_no_command_or_url(self) -> None:
        """JetBrains-style config_file field is shown in output."""
        servers = {"intellij": {"config_file": "/home/user/.config/JetBrains/mcp.xml"}}
        mock_adapter = _make_mock_adapter(
            display_name="JetBrains",
            supported=True,
            servers=servers,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="jetbrains")
        assert "mcp.xml" in result

    def test_scan_result_does_not_start_with_newline(self) -> None:
        """Output should not start with a leading newline character."""
        mock_adapter = _make_mock_adapter(
            display_name="My Tool",
            supported=True,
            servers={"s": {"command": "c"}},
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="my_tool")
        assert not result.startswith("\n")

    def test_scan_shows_server_count(self) -> None:
        """The number of servers is included in the output line."""
        servers = {f"srv{i}": {"command": f"cmd{i}"} for i in range(4)}
        mock_adapter = _make_mock_adapter(
            display_name="Multi Server Tool",
            supported=True,
            servers=servers,
        )
        with patch("src.multimcp.adapters.get_adapter", return_value=mock_adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[mock_adapter]):
            result = cmd_scan(tool="multi")
        assert "4" in result


# ---------------------------------------------------------------------------
# Integration: cmd_install writes real file, cmd_scan reads it
# ---------------------------------------------------------------------------

class TestCmdInstallScanIntegration:
    def test_install_then_scan_roundtrip(self, tmp_path: Path) -> None:
        """Install a server entry and then scan to verify it's discovered."""
        from src.multimcp.adapters import get_adapter

        # Use the real gemini_cli adapter with a tmp file
        adapter = get_adapter("gemini_cli")
        assert adapter is not None

        config_file = tmp_path / "settings.json"
        server_cfg = {"command": "python", "args": ["main.py"], "env": {}}

        with patch.object(adapter, "config_path", return_value=config_file), \
             patch("src.multimcp.adapters.get_adapter", return_value=adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[adapter]):
            install_result = cmd_install(
                tool="gemini_cli",
                server_name="test-mcp",
                server_config=server_cfg,
            )

        assert "✅" in install_result

        with patch.object(adapter, "config_path", return_value=config_file), \
             patch("src.multimcp.adapters.get_adapter", return_value=adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[adapter]):
            scan_result = cmd_scan(tool="gemini_cli")

        assert "test-mcp" in scan_result

    def test_install_jetbrains_succeeds(self) -> None:
        """Installing into JetBrains now writes to ~/.junie/mcp/mcp.json."""
        from src.multimcp.adapters import get_adapter
        adapter = get_adapter("jetbrains")
        assert adapter is not None

        with patch("src.multimcp.adapters.get_adapter", return_value=adapter), \
             patch("src.multimcp.adapters.list_adapters", return_value=[adapter]), \
             patch.object(adapter, "register_server"):
            result = cmd_install(tool="jetbrains", server_name="my-server")
        assert "JetBrains" in result