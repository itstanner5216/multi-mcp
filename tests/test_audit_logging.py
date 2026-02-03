"""
Tests for audit logging integration.

Following TDD: RED phase - these tests should fail initially.
"""

import pytest
import os
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from src.multimcp.utils.audit import AuditLogger


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for audit logs."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def audit_logger(temp_log_dir):
    """Create an AuditLogger instance with temporary directory."""
    return AuditLogger(log_dir=temp_log_dir)


class TestAuditLogger:
    """Test suite for AuditLogger functionality."""

    def test_audit_logger_creates_log_directory(self, temp_log_dir):
        """Test that AuditLogger creates the log directory if it doesn't exist."""
        log_path = Path(temp_log_dir) / "audit_logs"
        assert not log_path.exists()

        AuditLogger(log_dir=str(log_path))

        assert log_path.exists()
        assert log_path.is_dir()

    def test_audit_logger_creates_jsonl_file(self, audit_logger, temp_log_dir):
        """Test that audit log file is created in JSONL format."""
        audit_logger.log_tool_call(
            tool_name="test_tool", server_name="test_server", arguments={"arg": "value"}
        )

        log_file = Path(temp_log_dir) / "audit.jsonl"
        assert log_file.exists()

    def test_log_tool_call_creates_valid_jsonl_entry(self, audit_logger, temp_log_dir):
        """Test that tool call logging creates valid JSONL entries."""
        audit_logger.log_tool_call(
            tool_name="calculator::add",
            server_name="calculator",
            arguments={"a": 5, "b": 3},
        )

        log_file = Path(temp_log_dir) / "audit.jsonl"
        with open(log_file, "r") as f:
            line = f.readline()
            entry = json.loads(line)

            assert entry["event_type"] == "tool_call"
            assert entry["tool_name"] == "calculator::add"
            assert entry["server_name"] == "calculator"
            assert entry["arguments"] == {"a": 5, "b": 3}
            assert "timestamp" in entry
            assert entry["status"] == "success"

    def test_log_tool_failure_creates_error_entry(self, audit_logger, temp_log_dir):
        """Test that tool failures are logged with error status."""
        audit_logger.log_tool_failure(
            tool_name="broken_tool",
            server_name="test_server",
            arguments={"arg": "value"},
            error="Connection timeout",
        )

        log_file = Path(temp_log_dir) / "audit.jsonl"
        with open(log_file, "r") as f:
            line = f.readline()
            entry = json.loads(line)

            assert entry["event_type"] == "tool_call"
            assert entry["status"] == "error"
            assert entry["error"] == "Connection timeout"

    def test_multiple_entries_are_appended(self, audit_logger, temp_log_dir):
        """Test that multiple log entries are appended correctly."""
        audit_logger.log_tool_call("tool1", "server1", {})
        audit_logger.log_tool_call("tool2", "server2", {})
        audit_logger.log_tool_failure("tool3", "server3", {}, "Error")

        log_file = Path(temp_log_dir) / "audit.jsonl"
        with open(log_file, "r") as f:
            lines = f.readlines()

        assert len(lines) == 3

        # All should be valid JSON
        for line in lines:
            entry = json.loads(line)
            assert "event_type" in entry
            assert "timestamp" in entry

    def test_log_rotation_works(self, temp_log_dir):
        """Test that log rotation works when file size exceeds limit."""
        # Create logger with small rotation size (1KB)
        audit_logger = AuditLogger(log_dir=temp_log_dir, rotation="1 KB")

        # Write enough entries to trigger rotation
        for i in range(100):
            audit_logger.log_tool_call(
                tool_name=f"tool_{i}",
                server_name="server",
                arguments={"large_data": "x" * 100},
            )

        # Check that rotated files exist
        log_files = list(Path(temp_log_dir).glob("audit*.jsonl*"))
        assert len(log_files) > 1  # Original + at least one rotated file

    def test_timestamp_format_is_iso8601(self, audit_logger, temp_log_dir):
        """Test that timestamps use ISO 8601 format."""
        audit_logger.log_tool_call("test_tool", "server", {})

        log_file = Path(temp_log_dir) / "audit.jsonl"
        with open(log_file, "r") as f:
            entry = json.loads(f.readline())

        # Should parse as ISO format
        timestamp = datetime.fromisoformat(entry["timestamp"])
        assert isinstance(timestamp, datetime)
