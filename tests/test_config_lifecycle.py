"""
Tests for configuration lifecycle and idle-disconnect behavior.

Covers:
  6a. Config Lifecycle:
  - YAML bootstrap sets tool_filter → add_pending_server preserves it (setdefault)
  - All tools disabled in YAML → explicit deny-all filter → _is_tool_allowed returns False
  - Server connects → disconnects idle → config restored in pending_configs → reconnects
  - Server connects → disconnects → proxy tool mappings cleared (client=None)
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp import types
from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, ToolMapping


# ─── helpers ────────────────────────────────────────────────────────────────


def _make_tool(name: str) -> types.Tool:
    """Create a minimal Tool object with the given name."""
    return types.Tool(
        name=name,
        description="test tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_proxy_with_tools(
    server_name: str, tool_names: list, *, connected: bool = True
) -> tuple:
    """Create a MCPProxyServer pre-loaded with tools.

    Pass connected=True to set a mock client (tools appear in _list_tools).
    Pass connected=False for client=None (lazy/pending state).
    """
    cm = MCPClientManager()
    proxy = MCPProxyServer(cm)
    mock_client = MagicMock() if connected else None
    for t in tool_names:
        key = proxy._make_key(server_name, t)
        proxy.tool_to_server[key] = ToolMapping(
            server_name=server_name,
            client=mock_client,
            tool=_make_tool(key),
        )
    return proxy, cm


# ─── Scenario 1: YAML bootstrap filter preserved by add_pending_server ───────


class TestBootstrapFilterPreservation:
    """Verify that _bootstrap_from_yaml-style manual filter assignment is NOT
    overwritten when add_pending_server is subsequently called for the same server."""

    def test_bootstrap_sets_tool_filter_then_add_pending_preserves_it(self):
        """Bootstrap sets tool_filters["srv"], then add_pending_server keeps it unchanged."""
        cm = MCPClientManager()

        # Simulate what _bootstrap_from_yaml does: directly assign the filter
        cm.tool_filters["srv"] = {"allow": ["tool_a"], "deny": []}

        # Now simulate add_pending_server being called for the same server
        # (as happens during run() after bootstrap). It uses setdefault, so it
        # must NOT overwrite the previously assigned filter.
        cm.add_pending_server("srv", {"command": "node"})

        # Filter must remain as set by bootstrap, not replaced with None
        # (which is what add_pending_server would set from {"command": "node"})
        assert cm.tool_filters["srv"] == {"allow": ["tool_a"], "deny": []}

    def test_setdefault_does_not_overwrite_existing_filter(self):
        """Calling add_pending_server when a filter is already present leaves it alone."""
        cm = MCPClientManager()
        existing_filter = {"allow": ["alpha", "beta"], "deny": []}
        cm.tool_filters["srv"] = existing_filter

        # add_pending_server's setdefault should be a no-op for an existing key
        cm.add_pending_server("srv", {"command": "python", "tools": ["gamma"]})

        # Still the original filter — 'gamma' from the new config is NOT merged
        assert cm.tool_filters["srv"] == existing_filter

    def test_add_pending_server_sets_filter_when_none_exists(self):
        """add_pending_server does install a filter when no prior filter exists."""
        cm = MCPClientManager()

        # No pre-existing filter
        cm.add_pending_server("srv", {"command": "node", "tools": ["tool_x"]})

        # Filter is now set from the config tools key
        assert cm.tool_filters["srv"] == {"allow": ["tool_x"], "deny": []}


# ─── Scenario 2: All tools disabled → deny-all filter ───────────────────────


class TestDenyAllFilter:
    """Deny-all filter (allow=[], deny=['*']) blocks every tool."""

    def test_all_disabled_filter_denies_all_tools(self):
        """Explicit deny-all filter blocks any named tool."""
        deny_all = {"allow": [], "deny": ["*"]}
        assert MCPProxyServer._is_tool_allowed("tool_a", deny_all) is False
        assert MCPProxyServer._is_tool_allowed("anything", deny_all) is False
        assert MCPProxyServer._is_tool_allowed("*", deny_all) is False

    def test_empty_allow_list_denies_all_tools(self):
        """Empty allow list (no wildcard, no deny wildcard) also blocks all tools."""
        filter_cfg = {"allow": [], "deny": []}
        assert MCPProxyServer._is_tool_allowed("tool_a", filter_cfg) is False

    def test_deny_wildcard_overrides_explicit_allow(self):
        """deny=['*'] blocks tools even when the tool appears in the allow list."""
        filter_cfg = {"allow": ["tool_a"], "deny": ["*"]}
        assert MCPProxyServer._is_tool_allowed("tool_a", filter_cfg) is False

    def test_none_filter_allows_everything(self):
        """None filter (no filtering configured) permits any tool."""
        assert MCPProxyServer._is_tool_allowed("anything", None) is True

    @pytest.mark.asyncio
    async def test_bootstrap_deny_all_results_in_empty_list_tools(self):
        """Proxy loaded with deny-all filter exposes zero tools in _list_tools."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)

        # No tools registered at all — simulates deny-all (nothing passes filter)
        result = await proxy._list_tools(None)
        assert result.root.tools == []


# ─── Scenario 3: Idle disconnect restores pending_configs ────────────────────


class TestIdleDisconnectRestoresPendingConfigs:
    """After idle timeout, server config must return to pending_configs."""

    @pytest.mark.asyncio
    async def test_idle_disconnect_restores_pending_config(self):
        """Disconnecting an idle server moves its config back to pending_configs."""
        cm = MCPClientManager()
        server_cfg = {"command": "node", "args": ["server.js"]}
        cm.server_configs["srv"] = server_cfg
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01  # 10 ms — expires immediately
        cm.last_used["srv"] = 0  # epoch: far in the past

        await cm._disconnect_idle_servers()

        assert "srv" not in cm.clients
        assert "srv" in cm.pending_configs
        assert cm.pending_configs["srv"] == server_cfg

    @pytest.mark.asyncio
    async def test_idle_disconnect_removes_from_clients(self):
        """Idled server is removed from the active clients dict."""
        cm = MCPClientManager()
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        assert "srv" not in cm.clients

    @pytest.mark.asyncio
    async def test_idle_disconnect_clears_last_used(self):
        """Idled server's last_used entry is removed after disconnect."""
        cm = MCPClientManager()
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        assert "srv" not in cm.last_used

    @pytest.mark.asyncio
    async def test_idle_disconnect_clears_creation_lock(self):
        """Idled server's _creation_locks entry is cleaned up."""
        cm = MCPClientManager()
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0
        # Ensure a lock exists so we can verify it's removed
        cm._creation_locks["srv"] = asyncio.Lock()

        await cm._disconnect_idle_servers()

        assert "srv" not in cm._creation_locks


# ─── Scenario 4: Idle disconnect fires callback ──────────────────────────────


class TestIdleDisconnectCallback:
    """_on_server_disconnected callback is called when a server idles out."""

    @pytest.mark.asyncio
    async def test_idle_disconnect_callback_fires(self):
        """Callback is awaited with the server name when it idles out."""
        callback = AsyncMock()
        cm = MCPClientManager(on_server_disconnected=callback)
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        callback.assert_awaited_once_with("srv")

    @pytest.mark.asyncio
    async def test_idle_disconnect_callback_not_called_when_not_idle(self):
        """Callback is NOT called for a recently used server."""
        callback = AsyncMock()
        cm = MCPClientManager(on_server_disconnected=callback)
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 9999  # far future
        cm.last_used["srv"] = time.monotonic()

        await cm._disconnect_idle_servers()

        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idle_disconnect_no_callback_when_none_set(self):
        """No error when _on_server_disconnected is None."""
        cm = MCPClientManager()  # no callback
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        # Should not raise
        await cm._disconnect_idle_servers()

        assert "srv" not in cm.clients


# ─── Scenario 5: Idle disconnect preserves tool_filters ─────────────────────


class TestIdleDisconnectPreservesToolFilter:
    """tool_filters must survive an idle disconnect so they apply on reconnect."""

    @pytest.mark.asyncio
    async def test_idle_disconnect_preserves_tool_filter(self):
        """tool_filters entry is NOT removed when a server idles out."""
        cm = MCPClientManager()
        filter_cfg = {"allow": ["tool_a"], "deny": []}
        cm.tool_filters["srv"] = filter_cfg
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # tool_filters must still be present with the original config
        assert "srv" in cm.tool_filters
        assert cm.tool_filters["srv"] == filter_cfg

    @pytest.mark.asyncio
    async def test_idle_disconnect_preserves_idle_timeouts(self):
        """idle_timeouts entry is kept so the rule applies on subsequent connects."""
        cm = MCPClientManager()
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 300
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # idle_timeouts stays so the timer is still enforced after reconnect
        assert "srv" in cm.idle_timeouts
        assert cm.idle_timeouts["srv"] == 300


# ─── Scenario 6: Proxy tool mappings cleared after disconnect callback ────────


class TestProxyMappingsClearedAfterDisconnect:
    """After _on_server_disconnected, all ToolMapping.client values are None
    so tools are flagged as lazy-pending (not stale live references)."""

    @pytest.mark.asyncio
    async def test_proxy_tool_mappings_cleared_after_disconnect_callback(self):
        """ToolMapping.client is set to None by proxy._on_server_disconnected."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)
        mock_client = MagicMock()

        # Register tools with a live mock client
        for tool_name in ["tool_a", "tool_b"]:
            key = proxy._make_key("srv", tool_name)
            proxy.tool_to_server[key] = ToolMapping(
                server_name="srv",
                client=mock_client,
                tool=_make_tool(key),
            )

        # Wire the callback as the real code does in multi_mcp.run()
        cm._on_server_disconnected = proxy._on_server_disconnected

        # Trigger disconnect
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # All tool mappings for "srv" must now have client=None
        for key, mapping in proxy.tool_to_server.items():
            if mapping.server_name == "srv":
                assert mapping.client is None, (
                    f"Expected client=None for {key} after disconnect"
                )

    @pytest.mark.asyncio
    async def test_no_stale_live_tool_mappings_after_disconnect(self):
        """After disconnect, no tool mapping for the server retains a live client."""
        proxy, cm = _make_proxy_with_tools("srv", ["alpha", "beta"], connected=True)

        # Confirm tools are initially "live" (client is not None)
        for key, mapping in proxy.tool_to_server.items():
            if mapping.server_name == "srv":
                assert mapping.client is not None

        # Wire callback and trigger idle disconnect
        cm._on_server_disconnected = proxy._on_server_disconnected
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # All should be reset to None
        live_mappings = [
            key for key, m in proxy.tool_to_server.items()
            if m.server_name == "srv" and m.client is not None
        ]
        assert live_mappings == [], (
            f"Found stale live tool mappings after disconnect: {live_mappings}"
        )

    @pytest.mark.asyncio
    async def test_other_server_tools_unaffected_by_disconnect(self):
        """Disconnecting 'srv' does not clear tool mappings for another server."""
        cm = MCPClientManager()
        proxy = MCPProxyServer(cm)
        mock_client_a = MagicMock()
        mock_client_b = MagicMock()

        for tool_name in ["tool_a"]:
            key = proxy._make_key("srv", tool_name)
            proxy.tool_to_server[key] = ToolMapping(
                server_name="srv", client=mock_client_a, tool=_make_tool(key)
            )
        for tool_name in ["tool_x"]:
            key = proxy._make_key("other_srv", tool_name)
            proxy.tool_to_server[key] = ToolMapping(
                server_name="other_srv", client=mock_client_b, tool=_make_tool(key)
            )

        cm._on_server_disconnected = proxy._on_server_disconnected
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # other_srv's tools must keep their live client reference
        for key, mapping in proxy.tool_to_server.items():
            if mapping.server_name == "other_srv":
                assert mapping.client is mock_client_b


# ─── Scenario 7: Reconnect after idle uses same filter ───────────────────────


class TestReconnectAfterIdleUsesFilter:
    """After idle disconnect the server is back in pending_configs with its filter
    intact, so get_or_create_client will reconnect correctly."""

    @pytest.mark.asyncio
    async def test_reconnect_after_idle_uses_same_filter(self):
        """Filter is preserved across idle-disconnect so it applies on reconnect."""
        cm = MCPClientManager()
        filter_cfg = {"allow": ["tool_a"], "deny": []}
        cm.tool_filters["srv"] = filter_cfg
        cm.server_configs["srv"] = {"command": "node"}
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # Server is pending again with the original config
        assert "srv" in cm.pending_configs
        assert cm.pending_configs["srv"] == {"command": "node"}

        # Filter is still the same
        assert cm.tool_filters["srv"] == filter_cfg

        # Simulate get_or_create_client calling _create_single_client on reconnect
        mock_reconnected = AsyncMock()

        async def fake_create(name, config):
            cm.clients[name] = mock_reconnected

        cm._create_single_client = fake_create

        client = await cm.get_or_create_client("srv")

        assert client is mock_reconnected
        # Filter must still be the same — not replaced during reconnect
        assert cm.tool_filters["srv"] == filter_cfg

    @pytest.mark.asyncio
    async def test_pending_config_available_for_reconnect_after_idle(self):
        """After idle disconnect, pending_configs[srv] holds the original config dict."""
        original_cfg = {"command": "python", "args": ["server.py"]}
        cm = MCPClientManager()
        cm.server_configs["srv"] = original_cfg
        cm.clients["srv"] = AsyncMock()
        cm.idle_timeouts["srv"] = 0.01
        cm.last_used["srv"] = 0

        await cm._disconnect_idle_servers()

        # The pending config should be exactly the server_configs entry
        assert cm.pending_configs["srv"] is original_cfg
