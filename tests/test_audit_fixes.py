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

    def test_handles_list_with_sensitive_dicts(self):
        """Lists containing dicts with sensitive keys should be sanitized."""
        args = {"items": [{"api_key": "secret", "name": "test"}, {"token": "abc"}]}
        sanitized = _sanitize_arguments(args)
        assert sanitized["items"][0]["api_key"] == "***REDACTED***"
        assert sanitized["items"][0]["name"] == "test"
        assert sanitized["items"][1]["token"] == "***REDACTED***"

    def test_handles_plain_list_values(self):
        """Lists of non-dict values should pass through unchanged."""
        args = {"tags": ["a", "b", "c"], "count": 3}
        sanitized = _sanitize_arguments(args)
        assert sanitized["tags"] == ["a", "b", "c"]
        assert sanitized["count"] == 3

    def test_redacts_private_key(self):
        args = {"private_key": "-----BEGIN RSA-----", "name": "test"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["private_key"] == "***REDACTED***"

    def test_redacts_access_key(self):
        args = {"access_key": "AKIA1234", "region": "us-east-1"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["access_key"] == "***REDACTED***"
        assert sanitized["region"] == "us-east-1"

    def test_redacts_connection_string(self):
        args = {"connection_string": "postgres://user:pass@host/db"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["connection_string"] == "***REDACTED***"

    def test_redacts_signing_key(self):
        args = {"signing_key": "hmac-secret", "alg": "HS256"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["signing_key"] == "***REDACTED***"
        assert sanitized["alg"] == "HS256"

    def test_redacts_ssh_key(self):
        args = {"ssh_key": "ssh-rsa AAAA...", "host": "example.com"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["ssh_key"] == "***REDACTED***"

    def test_redacts_cookie(self):
        args = {"cookie": "session=abc123", "path": "/"}
        sanitized = _sanitize_arguments(args)
        assert sanitized["cookie"] == "***REDACTED***"

    def test_deeply_nested_sanitization(self):
        """Three-level nesting should still redact sensitive keys."""
        args = {
            "config": {
                "database": {
                    "connection_string": "postgres://secret",
                    "pool_size": 5,
                }
            }
        }
        sanitized = _sanitize_arguments(args)
        assert sanitized["config"]["database"]["connection_string"] == "***REDACTED***"
        assert sanitized["config"]["database"]["pool_size"] == 5

    def test_list_of_lists_with_dicts(self):
        """Nested lists containing dicts with sensitive keys."""
        args = {"data": [{"items": [{"token": "secret"}]}]}
        sanitized = _sanitize_arguments(args)
        assert sanitized["data"][0]["items"][0]["token"] == "***REDACTED***"


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
