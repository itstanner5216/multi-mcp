"""
Tests for Task 2: Port + Logging Cleanup
- Default port should be 8085
- Config loading should use logger instead of print()
"""

import pytest
import tempfile
import json
import os
from unittest.mock import patch, MagicMock
from src.multimcp.multi_mcp import MultiMCP, MCPSettings


class TestDefaultPort:
    """Test that default port is 8085."""

    def test_mcp_settings_default_port_is_8085(self):
        """MCPSettings should default to port 8085."""
        settings = MCPSettings()
        assert settings.port == 8085

    def test_multi_mcp_uses_8085_by_default(self):
        """MultiMCP should use port 8085 when not specified."""
        server = MultiMCP()
        assert server.settings.port == 8085

    def test_port_can_be_overridden(self):
        """Port can still be overridden via settings."""
        server = MultiMCP(port=9090)
        assert server.settings.port == 9090


class TestLoggingInConfigLoading:
    """Test that config loading uses logger instead of print()."""

    def test_missing_config_file_logs_error(self):
        """When config file doesn't exist, should log error instead of print."""
        server = MultiMCP()

        # Mock the logger to capture calls
        with patch.object(server.logger, "error") as mock_error:
            result = server.load_mcp_config(path="/nonexistent/path.json")

            assert result is None
            assert mock_error.called
            # Check that error message contains the path
            call_args = mock_error.call_args[0][0]
            assert "/nonexistent/path.json" in call_args

    def test_invalid_json_logs_error(self):
        """When JSON is invalid, should log error instead of print."""
        server = MultiMCP()

        # Create temp file with invalid JSON
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            f.write("{invalid json content")
            temp_path = f.name

        try:
            with patch.object(server.logger, "error") as mock_error:
                result = server.load_mcp_config(path=temp_path)

                assert result is None
                assert mock_error.called
                # Check that error message mentions JSON parsing
                call_args = mock_error.call_args[0][0]
                assert "JSON" in call_args or "parsing" in call_args.lower()
        finally:
            os.unlink(temp_path)

    def test_valid_config_loads_without_errors(self):
        """Valid config should load successfully without logging errors."""
        server = MultiMCP()

        # Create temp file with valid JSON
        config_data = {
            "mcpServers": {"test": {"command": "python", "args": ["test.py"]}}
        }

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            result = server.load_mcp_config(path=temp_path)

            assert result is not None
            assert result == config_data
        finally:
            os.unlink(temp_path)
