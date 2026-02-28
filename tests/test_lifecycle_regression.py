"""Regression tests for Phase 2A: lifecycle and filtering fixes.

Covers:
  R9 - Scenario 1: Filter lifecycle (_bootstrap_from_yaml → tool_filters → _is_tool_allowed)
  R2 - Scenario 2: All-disabled server → explicit deny-all filter (zero tools exposed)
  N3 - Scenario 3 & 7: Concurrent get_or_create_client() → only one connection, no race
  R7 - Scenario 4: /mcp_tools parity (get_filtered_tools == _list_tools)
  R4 - Scenario 5: record_usage() called after successful _call_tool()
  N1 - Scenario 6: /messages/ requires auth (401 without token, not-401 with token)
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping
from src.multimcp.multi_mcp import MultiMCP, MCPSettings
from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig, ToolEntry
from mcp import types


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_tool(name: str) -> types.Tool:
    """Create a minimal Tool object with the given name."""
    return types.Tool(
        name=name,
        description="test tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_proxy_with_tools(
    server_name: str, tool_names: list[str], *, connected: bool = False
) -> tuple[MCPProxyServer, MCPClientManager]:
    """Create a proxy pre-loaded with tools but NO real clients.

    Uses the direct constructor (not MCPProxyServer.create) so no network
    connections are attempted.  Pass connected=True to set a mock client
    so tools appear in _list_tools (which filters out client=None).
    """
    cm = MCPClientManager()
    proxy = MCPProxyServer(cm)
    mock_client = object() if connected else None
    for t in tool_names:
        key = proxy._make_key(server_name, t)
        proxy.tool_to_server[key] = ToolMapping(
            server_name=server_name,
            client=mock_client,
            tool=_make_tool(key),
        )
    return proxy, cm


# ─── Scenario 1: Filter lifecycle ───────────────────────────────────────────

class TestFilterLifecycle:
    """Scenario 1: add_pending_server sets tool_filters correctly."""

    def test_allow_list_shorthand_stored_in_tool_filters(self):
        """add_pending_server with tools list → allow filter stored."""
        cm = MCPClientManager()
        cm.add_pending_server("srv", {"command": "node", "tools": ["tool_a", "tool_b"]})
        assert cm.tool_filters["srv"] == {"allow": ["tool_a", "tool_b"], "deny": []}

    def test_no_tools_key_means_no_filter(self):
        """add_pending_server with no 'tools' key → filter is None (all allowed)."""
        cm = MCPClientManager()
        cm.add_pending_server("srv", {"command": "node"})
        assert cm.tool_filters["srv"] is None

    def test_tools_dict_format_stored_correctly(self):
        """add_pending_server with tools dict format → allow/deny stored."""
        cm = MCPClientManager()
        cm.add_pending_server(
            "srv",
            {"command": "node", "tools": {"allow": ["tool_a"], "deny": ["tool_b"]}},
        )
        assert cm.tool_filters["srv"] == {"allow": ["tool_a"], "deny": ["tool_b"]}

    def test_is_tool_allowed_with_allow_list_permits_listed_tool(self):
        """_is_tool_allowed returns True for a tool in the allow list."""
        assert (
            MCPProxyServer._is_tool_allowed("tool_a", {"allow": ["tool_a"], "deny": []})
            is True
        )

    def test_is_tool_allowed_with_allow_list_blocks_unlisted_tool(self):
        """_is_tool_allowed returns False for a tool not in the allow list."""
        assert (
            MCPProxyServer._is_tool_allowed("tool_b", {"allow": ["tool_a"], "deny": []})
            is False
        )

    def test_is_tool_allowed_with_none_filter_permits_everything(self):
        """_is_tool_allowed with None filter → all tools allowed."""
        assert MCPProxyServer._is_tool_allowed("anything", None) is True

    def test_is_tool_allowed_deny_list_blocks_explicitly_denied_tool(self):
        """_is_tool_allowed with deny list blocks the named tool."""
        assert (
            MCPProxyServer._is_tool_allowed(
                "bad_tool", {"allow": ["*"], "deny": ["bad_tool"]}
            )
            is False
        )

    def test_pending_server_config_saved(self):
        """add_pending_server stores config in pending_configs."""
        cm = MCPClientManager()
        cfg = {"command": "node", "args": ["server.js"]}
        cm.add_pending_server("my_srv", cfg)
        assert "my_srv" in cm.pending_configs
        assert cm.pending_configs["my_srv"] == cfg


# ─── Scenario 2: All-disabled server ────────────────────────────────────────

class TestAllDisabledServer:
    """Scenario 2: Server with all tools enabled:false → deny-all filter."""

    @pytest.mark.asyncio
    async def test_all_disabled_yaml_results_in_deny_all_filter(self):
        """_bootstrap_from_yaml logic: all tools disabled → deny-all filter."""
        from src.multimcp.cache_manager import get_enabled_tools

        config = MultiMCPConfig(
            servers={
                "srv": ServerConfig(
                    command="node",
                    tools={
                        "tool_a": ToolEntry(enabled=False),
                        "tool_b": ToolEntry(enabled=False),
                    },
                )
            }
        )
        cm = MCPClientManager()

        # Replicate the _bootstrap_from_yaml filter logic
        for server_name, server_config in config.servers.items():
            enabled = get_enabled_tools(config, server_name)
            if enabled:
                cm.tool_filters[server_name] = {"allow": list(enabled), "deny": []}
            else:
                cm.tool_filters[server_name] = {"allow": [], "deny": ["*"]}

        filter_cfg = cm.tool_filters["srv"]
        assert MCPProxyServer._is_tool_allowed("tool_a", filter_cfg) is False
        assert MCPProxyServer._is_tool_allowed("tool_b", filter_cfg) is False

    def test_is_tool_allowed_empty_allow_list_denies_all(self):
        """Empty allow list (no wildcard) → deny all tools."""
        assert (
            MCPProxyServer._is_tool_allowed("anything", {"allow": [], "deny": []})
            is False
        )

    def test_is_tool_allowed_deny_wildcard_blocks_any_tool(self):
        """Deny wildcard '*' blocks all tools regardless of allow list."""
        assert (
            MCPProxyServer._is_tool_allowed("anything", {"allow": [], "deny": ["*"]})
            is False
        )

    def test_is_tool_allowed_deny_wildcard_overrides_allow(self):
        """Deny wildcard '*' takes precedence over allow list."""
        assert (
            MCPProxyServer._is_tool_allowed(
                "tool_a", {"allow": ["tool_a"], "deny": ["*"]}
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_zero_tools_in_list_tools_when_all_disabled(self):
        """Proxy with no tools registered → _list_tools returns empty list."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)
        # No tools registered — simulates all-disabled server
        result = await proxy._list_tools(None)
        # _list_tools returns types.ServerResult; the actual payload is in .root
        assert result.root.tools == []


# ─── Scenario 3 & 7: Concurrent lazy connect ─────────────────────────────────

class TestConcurrentLazyConnect:
    """Scenarios 3 & 7: Concurrent get_or_create_client() → one connection, no errors."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_only_create_one_connection(self):
        """Three concurrent get_or_create_client() calls create only one connection."""
        cm = MCPClientManager()
        cm.pending_configs["srv"] = {"command": "node", "args": []}

        connection_count = 0
        mock_client = MagicMock()

        async def fake_create(name, config):
            nonlocal connection_count
            connection_count += 1
            await asyncio.sleep(0.05)  # Simulate connection delay
            cm.clients[name] = mock_client

        cm._create_single_client = fake_create

        results = await asyncio.gather(
            cm.get_or_create_client("srv"),
            cm.get_or_create_client("srv"),
            cm.get_or_create_client("srv"),
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]
        assert not errors, f"Unexpected errors: {errors}"
        assert connection_count == 1, (
            f"Expected exactly 1 connection attempt, got {connection_count}"
        )

    @pytest.mark.asyncio
    async def test_concurrent_calls_all_return_same_client(self):
        """All concurrent get_or_create_client() calls return the identical client."""
        cm = MCPClientManager()
        cm.pending_configs["srv"] = {"command": "node", "args": []}

        mock_client = MagicMock()

        async def fake_create(name, config):
            await asyncio.sleep(0.02)
            cm.clients[name] = mock_client

        cm._create_single_client = fake_create

        results = await asyncio.gather(
            cm.get_or_create_client("srv"),
            cm.get_or_create_client("srv"),
            return_exceptions=True,
        )

        assert all(r is mock_client for r in results), (
            "All callers should receive the same client instance"
        )

    @pytest.mark.asyncio
    async def test_concurrent_no_key_error_on_pending_pop(self):
        """Concurrent access must not raise KeyError from pending_configs.pop()."""
        cm = MCPClientManager()
        cm.pending_configs["srv"] = {"command": "node"}
        mock_client = MagicMock()

        async def fake_create(name, config):
            await asyncio.sleep(0.01)
            cm.clients[name] = mock_client

        cm._create_single_client = fake_create

        results = await asyncio.gather(
            cm.get_or_create_client("srv"),
            cm.get_or_create_client("srv"),
            return_exceptions=True,
        )

        key_errors = [r for r in results if isinstance(r, KeyError)]
        assert not key_errors, f"KeyError raised during concurrent access: {key_errors}"

    @pytest.mark.asyncio
    async def test_creation_lock_exists_after_first_call(self):
        """A per-server creation lock is lazily initialized."""
        cm = MCPClientManager()
        # Lock should be created on first access
        lock = cm._get_creation_lock("new_server")
        assert lock is not None
        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_same_lock_returned_for_same_server(self):
        """_get_creation_lock returns the same lock object for the same server name."""
        cm = MCPClientManager()
        lock1 = cm._get_creation_lock("srv")
        lock2 = cm._get_creation_lock("srv")
        assert lock1 is lock2

    @pytest.mark.asyncio
    async def test_unknown_server_raises_key_error(self):
        """get_or_create_client raises KeyError when server not in clients or pending."""
        cm = MCPClientManager()
        with pytest.raises(KeyError, match="Unknown server"):
            await cm.get_or_create_client("nonexistent_server")


# ─── Scenario 4: /mcp_tools parity ──────────────────────────────────────────

class TestMcpToolsParity:
    """Scenario 4: get_filtered_tools() and _list_tools() show the same tools."""

    @pytest.mark.asyncio
    async def test_get_filtered_tools_matches_list_tools_tool_names(self):
        """get_filtered_tools and _list_tools both read from tool_to_server."""
        proxy, cm = _make_proxy_with_tools("srv", ["tool_a", "tool_b"], connected=True)

        # get_filtered_tools() → grouped by server, tool names are the unnamespaced part
        filtered = proxy.get_filtered_tools()
        assert set(filtered.get("srv", [])) == {"tool_a", "tool_b"}

        # _list_tools() → types.ServerResult; actual payload in .root.tools
        result = await proxy._list_tools(None)
        tool_names_in_list = {
            proxy._split_key(t.name)[1] for t in result.root.tools
        }
        assert tool_names_in_list == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_get_filtered_tools_same_count_as_list_tools(self):
        """get_filtered_tools and _list_tools expose the same number of tools."""
        proxy, cm = _make_proxy_with_tools("srv", ["alpha", "beta", "gamma"], connected=True)

        filtered = proxy.get_filtered_tools()
        total_filtered = sum(len(v) for v in filtered.values())

        # _list_tools returns types.ServerResult; actual tools list in .root.tools
        result = await proxy._list_tools(None)
        assert total_filtered == len(result.root.tools)

    @pytest.mark.asyncio
    async def test_get_filtered_tools_excludes_tools_not_in_registry(self):
        """Only tools in tool_to_server appear in get_filtered_tools."""
        proxy, cm = _make_proxy_with_tools("srv", ["visible_tool"])

        filtered = proxy.get_filtered_tools()
        assert "invisible_tool" not in filtered.get("srv", [])
        assert "visible_tool" in filtered.get("srv", [])

    @pytest.mark.asyncio
    async def test_get_filtered_tools_groups_by_server(self):
        """get_filtered_tools correctly groups tools under their server name."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)

        # Two servers with different tools
        for t in ["tool_a", "tool_b"]:
            key = proxy._make_key("server_one", t)
            proxy.tool_to_server[key] = ToolMapping(
                server_name="server_one", client=None, tool=_make_tool(key)
            )
        for t in ["tool_x"]:
            key = proxy._make_key("server_two", t)
            proxy.tool_to_server[key] = ToolMapping(
                server_name="server_two", client=None, tool=_make_tool(key)
            )

        filtered = proxy.get_filtered_tools()
        assert set(filtered.get("server_one", [])) == {"tool_a", "tool_b"}
        assert set(filtered.get("server_two", [])) == {"tool_x"}

    @pytest.mark.asyncio
    async def test_mcp_tools_endpoint_returns_same_data(self):
        """MultiMCP.handle_mcp_tools uses get_filtered_tools for its response."""
        proxy, cm = _make_proxy_with_tools("srv", ["my_tool"])
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18085)
        app.proxy = proxy

        starlette_app = app.create_starlette_app()
        client = TestClient(starlette_app)

        response = client.get("/mcp_tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "my_tool" in data["tools"].get("srv", [])


# ─── Scenario 5: Idle timer refresh ─────────────────────────────────────────

class TestIdleTimerRefresh:
    """Scenario 5: Successful _call_tool() updates last_used timestamp."""

    @pytest.mark.asyncio
    async def test_successful_tool_call_updates_last_used(self):
        """After _call_tool() succeeds, client_manager.last_used is updated."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)

        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = False
        mock_client.call_tool = AsyncMock(return_value=mock_result)

        tool_key = proxy._make_key("srv", "my_tool")
        proxy.tool_to_server[tool_key] = ToolMapping(
            server_name="srv",
            client=mock_client,
            tool=_make_tool(tool_key),
        )

        before = time.monotonic()

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=tool_key, arguments={}),
        )
        await proxy._call_tool(req)

        assert "srv" in cm.last_used, (
            "last_used should be set for 'srv' after a successful tool call"
        )
        assert cm.last_used["srv"] >= before, (
            "last_used timestamp should be >= the time before the call"
        )

    @pytest.mark.asyncio
    async def test_last_used_not_set_for_unknown_tool(self):
        """_call_tool for an unknown tool does not update last_used."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="nonexistent__tool", arguments={}),
        )
        await proxy._call_tool(req)

        assert "nonexistent" not in cm.last_used

    @pytest.mark.asyncio
    async def test_record_usage_updates_timestamp(self):
        """record_usage() directly updates the last_used dict."""
        cm = MCPClientManager()
        before = time.monotonic()
        cm.record_usage("my_server")
        assert "my_server" in cm.last_used
        assert cm.last_used["my_server"] >= before

    @pytest.mark.asyncio
    async def test_failed_tool_call_does_not_update_last_used(self):
        """_call_tool that raises an exception should not update last_used."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))

        tool_key = proxy._make_key("broken_srv", "fragile_tool")
        proxy.tool_to_server[tool_key] = ToolMapping(
            server_name="broken_srv",
            client=mock_client,
            tool=_make_tool(tool_key),
        )

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=tool_key, arguments={}),
        )
        result = await proxy._call_tool(req)

        # _call_tool returns types.ServerResult; actual payload in .root
        # Should return an error result, not raise
        assert result.root.isError is True
        # last_used should NOT be updated for failed calls (record_usage only on success)
        assert "broken_srv" not in cm.last_used


# ─── Scenario 6: Auth on /messages/ ─────────────────────────────────────────

class TestMessagesAuth:
    """Scenario 6: /messages/ endpoint requires auth when API key is configured."""

    @pytest.mark.asyncio
    async def test_messages_without_auth_returns_401(self, auth_app):
        """POST /messages/{session} without Authorization header → 401."""
        client = TestClient(auth_app.create_starlette_app(), raise_server_exceptions=False)
        response = client.post("/messages/test-session", json={})
        assert response.status_code == 401, (
            f"Expected 401 without auth, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_messages_with_valid_auth_is_not_401(self, auth_app):
        """POST /messages/{session} with valid Bearer token → NOT 401."""
        client = TestClient(auth_app.create_starlette_app(), raise_server_exceptions=False)
        response = client.post(
            "/messages/test-session",
            headers={"Authorization": "Bearer test-secret-key-12345"},
            json={},
        )
        assert response.status_code != 401, (
            f"Expected non-401 with valid auth, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_messages_with_wrong_token_returns_401(self, auth_app):
        """POST /messages/{session} with wrong token → 401."""
        client = TestClient(auth_app.create_starlette_app(), raise_server_exceptions=False)
        response = client.post(
            "/messages/test-session",
            headers={"Authorization": "Bearer wrong-token"},
            json={},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_messages_with_malformed_auth_header_returns_401(self, auth_app):
        """POST /messages/{session} with malformed auth header → 401."""
        client = TestClient(auth_app.create_starlette_app(), raise_server_exceptions=False)
        response = client.post(
            "/messages/test-session",
            headers={"Authorization": "test-secret-key-12345"},  # Missing 'Bearer '
            json={},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_messages_no_auth_required_when_disabled(self):
        """POST /messages/{session} without auth token → passes when auth disabled."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18086)
        app.proxy = MCPProxyServer(MCPClientManager())

        client = TestClient(app.create_starlette_app(), raise_server_exceptions=False)
        response = client.post("/messages/test-session", json={})
        # Should not be 401 when auth is disabled
        assert response.status_code != 401, (
            f"Expected non-401 when auth disabled, got {response.status_code}"
        )


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_app():
    """MultiMCP app with API key authentication enabled and a ready proxy."""
    app = MultiMCP(
        transport="sse",
        host="127.0.0.1",
        port=18085,
        api_key="test-secret-key-12345",
    )
    # Use direct constructor to avoid network calls
    app.proxy = MCPProxyServer(MCPClientManager())
    return app
