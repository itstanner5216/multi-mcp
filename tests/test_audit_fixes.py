"""Tests for audit logging fixes."""

import pytest
import json
from datetime import datetime
from pathlib import Path

from src.multimcp.utils.audit import _sanitize_arguments


class TestAuditSanitization:
    """Verify sensitive values are redacted in audit logs."""

    def test_redacts_api_key(self):
        args = {"api_key": "sk-secret-1234", "query": "hello"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["api_key"] == "***REDACTED***"
        assert sanitized["query"] == "hello"

    def test_redacts_token(self):
        args = {"token": "ghp_abc123", "repo": "my-repo"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["token"] == "***REDACTED***"
        assert sanitized["repo"] == "my-repo"

    def test_redacts_password(self):
        args = {"password": "hunter2", "username": "admin"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["password"] == "***REDACTED***"
        assert sanitized["username"] == "admin"

    def test_redacts_secret(self):
        args = {"client_secret": "abc", "client_id": "123"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["client_secret"] == "***REDACTED***"
        assert sanitized["client_id"] == "123"

    def test_case_insensitive_matching(self):
        args = {"API_KEY": "secret", "Api_Token": "secret"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["API_KEY"] == "***REDACTED***"
        assert sanitized["Api_Token"] == "***REDACTED***"

    def test_handles_nested_dicts(self):
        args = {"config": {"api_key": "secret", "name": "test"}}
        sanitized = _sanitize_arguments(args)
        assert sanitized["config"]["api_key"] == "***REDACTED***"
        assert sanitized["config"]["name"] == "test"

    def test_handles_none_args(self):
        assert _sanitize_arguments(None) is None

    def test_handles_non_dict(self):
        assert _sanitize_arguments("plain string") == "plain string"


class TestAuditJsonSerialization:
    """Verify json.dumps with default=str handles non-serializable types."""

    def test_handles_datetime_in_args(self):
        """json.dumps with default=str should handle datetime."""
        args = {"timestamp": datetime.now(), "name": "test"}
        # Should not raise
        result = json.dumps(args, default=str)
        assert "name" in result

    def test_handles_path_in_args(self):
        """json.dumps with default=str should handle Path objects."""
        args = {"path": Path("/tmp/test"), "name": "test"}
        result = json.dumps(args, default=str)
        assert "/tmp/test" in result
