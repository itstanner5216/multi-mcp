"""
Tests for CC agent final-pass fixes.

Covers:
- mcp_client.py: pending_configs restored on failure, idle disconnect ordering,
  close() clears clients, _filter_env str coercion, IPv6 link-local SSRF block
- utils/audit.py: _sanitize_arguments handles tuples/sets, close() guards _sink_id,
  _write_entry serialization fallback
- utils/config.py: AuditConfig defaults
- utils/keyword_matcher.py: match_triggers, extract_keywords_from_message
"""

import asyncio
import ipaddress
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.multimcp.mcp_client import (
    MCPClientManager,
    _filter_env,
    _validate_url,
    _PRIVATE_RANGES,
)
from src.multimcp.utils.audit import AuditLogger, _sanitize_arguments
from src.multimcp.utils.config import AuditConfig
from src.multimcp.utils.keyword_matcher import (
    extract_keywords_from_message,
    match_triggers,
)


# ---------------------------------------------------------------------------
# mcp_client: pending_configs restored on connection failure
# ---------------------------------------------------------------------------

class TestGetOrCreateClientRestoresConfig:
    """get_or_create_client must restore pending_configs on any connection failure."""

    @pytest.mark.asyncio
    async def test_config_restored_on_timeout(self):
        """TimeoutError must leave server retryable (config restored to pending_configs)."""
        manager = MCPClientManager(connection_timeout=0.001)
        config = {"command": "python", "args": []}
        manager.pending_configs["srv"] = config
        manager.server_configs["srv"] = config

        async def _slow(*_a, **_kw):
            await asyncio.sleep(10)

        with patch.object(manager, "_create_single_client", side_effect=_slow):
            with pytest.raises(asyncio.TimeoutError):
                await manager.get_or_create_client("srv")

        assert "srv" in manager.pending_configs, (
            "Config must be restored so the server can be retried after a timeout"
        )

    @pytest.mark.asyncio
    async def test_config_restored_on_generic_error(self):
        """Any Exception during connection must leave server retryable."""
        manager = MCPClientManager()
        config = {"command": "python", "args": []}
        manager.pending_configs["srv"] = config
        manager.server_configs["srv"] = config

        async def _fail(*_a, **_kw):
            raise RuntimeError("connection refused")

        with patch.object(manager, "_create_single_client", side_effect=_fail):
            with pytest.raises(RuntimeError):
                await manager.get_or_create_client("srv")

        assert "srv" in manager.pending_configs, (
            "Config must be restored so the server can be retried after an error"
        )

    @pytest.mark.asyncio
    async def test_missing_server_raises_key_error(self):
        """Unknown server name must raise KeyError (no config to restore)."""
        manager = MCPClientManager()
        with pytest.raises(KeyError):
            await manager.get_or_create_client("does_not_exist")


# ---------------------------------------------------------------------------
# mcp_client: _disconnect_idle_servers ordering
# ---------------------------------------------------------------------------

class TestDisconnectIdleOrdering:
    """pending_configs must be restored before stack.aclose() is awaited."""

    @pytest.mark.asyncio
    async def test_pending_configs_restored_before_aclose(self):
        """After del clients[name], server must be in pending_configs before any await."""
        manager = MCPClientManager()
        config = {"command": "python", "args": []}
        manager.server_configs["lazy"] = config
        manager.clients["lazy"] = AsyncMock()
        manager.idle_timeouts["lazy"] = 0.01
        manager.last_used["lazy"] = time.monotonic() - 5.0

        restored_during_close = {}

        async def _mock_close():
            # At the moment aclose() is called, pending_configs must already be set
            restored_during_close["lazy"] = "lazy" in manager.pending_configs

        mock_stack = AsyncMock()
        mock_stack.aclose = _mock_close
        manager.server_stacks["lazy"] = mock_stack

        await manager._disconnect_idle_servers()

        assert restored_during_close.get("lazy") is True, (
            "pending_configs['lazy'] must be set before stack.aclose() is awaited"
        )
        assert "lazy" not in manager.clients

    @pytest.mark.asyncio
    async def test_disconnected_server_is_retryable(self):
        """After idle disconnect, get_or_create_client must find config in pending_configs."""
        manager = MCPClientManager()
        config = {"command": "python", "args": []}
        manager.server_configs["lazy"] = config
        manager.clients["lazy"] = AsyncMock()
        manager.server_stacks["lazy"] = AsyncMock()
        manager.idle_timeouts["lazy"] = 0.01
        manager.last_used["lazy"] = time.monotonic() - 5.0

        await manager._disconnect_idle_servers()

        assert "lazy" in manager.pending_configs
        assert "lazy" not in manager.clients


# ---------------------------------------------------------------------------
# mcp_client: close() clears clients
# ---------------------------------------------------------------------------

class TestCloseClears:
    """close() must clear self.clients to avoid stale references."""

    @pytest.mark.asyncio
    async def test_close_clears_clients_dict(self):
        manager = MCPClientManager()
        manager.clients["srv1"] = AsyncMock()
        manager.clients["srv2"] = AsyncMock()
        # No stacks so close() just clears
        await manager.close()
        assert manager.clients == {}, "clients must be empty after close()"

    @pytest.mark.asyncio
    async def test_close_clears_server_stacks(self):
        manager = MCPClientManager()
        mock_stack = AsyncMock()
        manager.server_stacks["srv"] = mock_stack
        manager.clients["srv"] = AsyncMock()
        await manager.close()
        assert manager.server_stacks == {}
        mock_stack.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# mcp_client: _filter_env str coercion
# ---------------------------------------------------------------------------

class TestFilterEnvStrCoercion:
    """_filter_env must coerce all values to str."""

    def test_int_value_coerced_to_str(self):
        result = _filter_env({"PORT": 8080, "DEBUG": True})
        assert result["PORT"] == "8080"
        assert result["DEBUG"] == "True"

    def test_none_value_coerced_to_str(self):
        result = _filter_env({"SETTING": None})
        assert result["SETTING"] == "None"

    def test_protected_vars_still_removed(self):
        result = _filter_env({"PATH": "/usr/bin", "MY_VAR": 42})
        assert "PATH" not in result
        assert result["MY_VAR"] == "42"


# ---------------------------------------------------------------------------
# mcp_client: IPv6 link-local SSRF block
# ---------------------------------------------------------------------------

class TestIPv6LinkLocalBlocked:
    """_PRIVATE_RANGES must include fe80::/10 (IPv6 link-local)."""

    def test_fe80_range_present(self):
        fe80_net = ipaddress.ip_network("fe80::/10")
        assert fe80_net in _PRIVATE_RANGES, "fe80::/10 must be in _PRIVATE_RANGES"

    def test_fe80_address_is_in_range(self):
        fe80_addr = ipaddress.ip_address("fe80::1")
        fe80_net = ipaddress.ip_network("fe80::/10")
        assert fe80_addr in fe80_net

    @pytest.mark.asyncio
    async def test_validate_url_rejects_fe80(self):
        """URL resolving to fe80:: (IPv6 link-local) must be rejected."""
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = AsyncMock(
                return_value=[(None, None, None, None, ("fe80::1", 0, 0, 0))]
            )
            with pytest.raises(ValueError, match="private|internal"):
                await _validate_url("http://example.com/api")


# ---------------------------------------------------------------------------
# utils/audit: _sanitize_arguments handles tuples and sets
# ---------------------------------------------------------------------------

class TestSanitizeTuplesAndSets:
    """_sanitize_arguments must recursively sanitize tuples and sets."""

    def test_tuple_of_dicts_sanitized(self):
        args = ({"api_key": "secret"}, {"name": "test"})
        result = _sanitize_arguments(args)
        assert isinstance(result, tuple)
        assert result[0]["api_key"] == "***REDACTED***"
        assert result[1]["name"] == "test"

    def test_set_of_non_sensitive_values_passes_through(self):
        """Sets of non-dict values pass through (sets are not further sanitized)."""
        args = {"tags": {1, 2, 3}}
        result = _sanitize_arguments(args)
        assert isinstance(result["tags"], set)

    def test_frozenset_preserved(self):
        args = frozenset(["a", "b"])
        result = _sanitize_arguments(args)
        assert isinstance(result, frozenset)

    def test_nested_tuple_in_dict(self):
        # Use a non-sensitive key so the tuple itself is traversed
        args = {"request_params": ({"token": "secret"}, {"user": "alice"})}
        result = _sanitize_arguments(args)
        assert result["request_params"][0]["token"] == "***REDACTED***"
        assert result["request_params"][1]["user"] == "alice"

    def test_tuple_of_plain_values(self):
        args = ("hello", "world")
        result = _sanitize_arguments(args)
        assert result == ("hello", "world")


# ---------------------------------------------------------------------------
# utils/audit: AuditLogger.close() guards _sink_id
# ---------------------------------------------------------------------------

class TestAuditLoggerCloseGuard:
    """close() must not raise if _sink_id was never set."""

    def test_close_without_sink_id_does_not_raise(self):
        """If loguru.add() never ran, close() must be safe."""
        al = object.__new__(AuditLogger)  # bypass __init__
        # _sink_id is intentionally absent
        al.close()  # must not raise AttributeError


# ---------------------------------------------------------------------------
# utils/audit: _write_entry serialization fallback
# ---------------------------------------------------------------------------

class TestWriteEntryFallback:
    """_write_entry must not raise even for unserializable objects."""

    def test_write_entry_with_bad_str_object(self, tmp_path):
        class BadStr:
            def __repr__(self):
                raise RuntimeError("boom")
            def __str__(self):
                raise RuntimeError("boom")

        al = AuditLogger(log_dir=str(tmp_path))
        entry = {
            "timestamp": "2025-01-01T00:00:00+00:00",
            "event_type": "tool_call",
            "tool_name": "test",
            "server_name": "test",
            "status": "success",
            "arguments": BadStr(),
        }
        # Must not raise despite bad object
        al._write_entry(entry)
        al.close()


# ---------------------------------------------------------------------------
# utils/config: AuditConfig defaults
# ---------------------------------------------------------------------------

class TestAuditConfigDefaults:
    def test_default_log_dir(self):
        cfg = AuditConfig()
        assert cfg.log_dir == "./logs"

    def test_default_rotation(self):
        assert AuditConfig().rotation == "10 MB"

    def test_default_retention(self):
        assert AuditConfig().retention == "30 days"

    def test_custom_values(self):
        cfg = AuditConfig(log_dir="/tmp/logs", rotation="1 MB", retention="7 days", compression="zip")
        assert cfg.log_dir == "/tmp/logs"
        assert cfg.rotation == "1 MB"
        assert cfg.retention == "7 days"
        assert cfg.compression == "zip"


# ---------------------------------------------------------------------------
# utils/keyword_matcher: coverage
# ---------------------------------------------------------------------------

class TestKeywordMatcher:
    def test_match_triggers_true(self):
        assert match_triggers("What is the weather today?", ["weather", "forecast"]) is True

    def test_match_triggers_false(self):
        assert match_triggers("Tell me a joke", ["weather"]) is False

    def test_match_triggers_case_insensitive(self):
        assert match_triggers("WEATHER report", ["weather"]) is True

    def test_match_triggers_empty_triggers(self):
        assert match_triggers("anything", []) is False

    def test_extract_keywords_simple_string(self):
        msg = {"method": "tools/call", "params": {"name": "get_weather"}}
        text = extract_keywords_from_message(msg)
        assert "tools/call" in text
        assert "get_weather" in text

    def test_extract_keywords_nested(self):
        msg = {"params": {"arguments": {"location": "New York"}}}
        text = extract_keywords_from_message(msg)
        assert "New York" in text

    def test_extract_keywords_list_values(self):
        msg = {"tags": ["weather", "forecast"]}
        text = extract_keywords_from_message(msg)
        assert "weather" in text
        assert "forecast" in text

    def test_extract_keywords_ignores_non_string(self):
        msg = {"count": 42, "name": "test"}
        text = extract_keywords_from_message(msg)
        assert "test" in text
        # 42 (int) should not cause an error
