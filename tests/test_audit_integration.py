"""
Integration tests for audit logging with proxy.

Tests that audit logging is properly integrated into tool execution.
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from loguru import logger

from mcp import types
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.utils.audit import AuditLogger


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for audit logs."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_client_manager():
    """Create a mock client manager."""
    manager = Mock(spec=MCPClientManager)
    manager.clients = {}
    manager.pending_configs = {}
    return manager


@pytest.fixture
def proxy_with_audit(mock_client_manager, temp_log_dir):
    """Create a proxy with audit logging to temp directory."""
    proxy = MCPProxyServer(mock_client_manager)
    # Replace audit logger with one using temp directory
    proxy.audit_logger = AuditLogger(log_dir=temp_log_dir)
    return proxy


class TestAuditIntegration:
    """Test suite for audit logging integration with proxy."""

    @pytest.mark.asyncio
    async def test_successful_tool_call_is_logged(self, proxy_with_audit, temp_log_dir):
        """Test that successful tool calls are logged to audit.jsonl."""
        # Setup mock tool
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = types.CallToolResult(
            content=[types.TextContent(type="text", text="Result")]
        )

        tool = types.Tool(
            name="add", description="Add numbers", inputSchema={"type": "object"}
        )

        proxy_with_audit.tool_to_server["calculator__add"] = ToolMapping(
            server_name="calculator", client=mock_client, tool=tool
        )

        # Call tool
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="calculator__add", arguments={"a": 5, "b": 3}
            ),
        )

        await proxy_with_audit._call_tool(request)

        logger.complete()

        # Verify audit log entry
        log_file = Path(temp_log_dir) / "audit.jsonl"
        assert log_file.exists()

        with open(log_file, "r") as f:
            entry = json.loads(f.readline())

        assert entry["event_type"] == "tool_call"
        assert entry["tool_name"] == "add"  # Original name, not namespaced
        assert entry["server_name"] == "calculator"
        assert entry["arguments"] == {"a": 5, "b": 3}
        assert entry["status"] == "success"

    @pytest.mark.asyncio
    async def test_failed_tool_call_is_logged(self, proxy_with_audit, temp_log_dir):
        """Test that failed tool calls are logged with error status."""
        # Setup mock tool that fails
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = Exception("Connection timeout")

        tool = types.Tool(
            name="broken", description="Broken tool", inputSchema={"type": "object"}
        )

        proxy_with_audit.tool_to_server["test__broken"] = ToolMapping(
            server_name="test", client=mock_client, tool=tool
        )

        # Call tool
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="test__broken", arguments={"arg": "value"}
            ),
        )

        result = await proxy_with_audit._call_tool(request)

        # Verify error returned
        assert result.root.isError is True

        logger.complete()

        # Verify audit log entry
        log_file = Path(temp_log_dir) / "audit.jsonl"
        with open(log_file, "r") as f:
            entry = json.loads(f.readline())

        assert entry["event_type"] == "tool_call"
        assert entry["tool_name"] == "broken"  # Original name, not namespaced
        assert entry["server_name"] == "test"
        assert entry["status"] == "error"
        assert "Connection timeout" in entry["error"]

    @pytest.mark.asyncio
    async def test_tool_not_found_is_logged(self, proxy_with_audit, temp_log_dir):
        """Test that tool not found errors are logged."""
        # Call non-existent tool
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="nonexistent__tool", arguments={}),
        )

        result = await proxy_with_audit._call_tool(request)

        # Verify error returned
        assert result.root.isError is True

        logger.complete()

        # Verify audit log entry
        log_file = Path(temp_log_dir) / "audit.jsonl"
        with open(log_file, "r") as f:
            entry = json.loads(f.readline())

        assert entry["event_type"] == "tool_call"
        assert entry["tool_name"] == "nonexistent__tool"
        assert entry["server_name"] == "unknown"
        assert entry["status"] == "error"
        assert "not found" in entry["error"]
