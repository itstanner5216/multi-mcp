"""Tests for _on_server_disconnected resetting prompt and resource mappings."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from mcp import types

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import (
    MCPProxyServer,
    PromptMapping,
    ResourceMapping,
    ToolMapping,
)


def _make_mock_client():
    return AsyncMock()


def _make_proxy() -> MCPProxyServer:
    manager = MCPClientManager()
    proxy = MCPProxyServer(manager)
    return proxy


# ---------------------------------------------------------------------------
# Helpers to populate mappings
# ---------------------------------------------------------------------------

def _add_tool(proxy: MCPProxyServer, server: str, name: str, client):
    tool = types.Tool(name=name, description="t", inputSchema={"type": "object"})
    proxy.tool_to_server[name] = ToolMapping(server_name=server, client=client, tool=tool)


def _add_prompt(proxy: MCPProxyServer, server: str, name: str, client):
    prompt = types.Prompt(name=name, description="p")
    proxy.prompt_to_server[name] = PromptMapping(server_name=server, client=client, prompt=prompt)


def _add_resource(proxy: MCPProxyServer, server: str, name: str, client, uri: str = "file:///x"):
    resource = types.Resource(name=name, uri=uri)
    proxy.resource_to_server[name] = ResourceMapping(server_name=server, client=client, resource=resource)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDisconnectResetsPrompts:
    """Prompt mappings should have client=None after server disconnect."""

    @pytest.mark.asyncio
    async def test_prompt_client_reset_on_disconnect(self):
        proxy = _make_proxy()
        client = _make_mock_client()
        _add_prompt(proxy, "srv1", "srv1__my_prompt", client)

        await proxy._on_server_disconnected("srv1")

        assert proxy.prompt_to_server["srv1__my_prompt"].client is None

    @pytest.mark.asyncio
    async def test_multiple_prompts_same_server(self):
        proxy = _make_proxy()
        client = _make_mock_client()
        _add_prompt(proxy, "srv1", "srv1__p1", client)
        _add_prompt(proxy, "srv1", "srv1__p2", client)

        await proxy._on_server_disconnected("srv1")

        assert proxy.prompt_to_server["srv1__p1"].client is None
        assert proxy.prompt_to_server["srv1__p2"].client is None


class TestDisconnectResetsResources:
    """Resource mappings should have client=None after server disconnect."""

    @pytest.mark.asyncio
    async def test_resource_client_reset_on_disconnect(self):
        proxy = _make_proxy()
        client = _make_mock_client()
        _add_resource(proxy, "srv1", "srv1__my_res", client)

        await proxy._on_server_disconnected("srv1")

        assert proxy.resource_to_server["srv1__my_res"].client is None

    @pytest.mark.asyncio
    async def test_multiple_resources_same_server(self):
        proxy = _make_proxy()
        client = _make_mock_client()
        _add_resource(proxy, "srv1", "srv1__r1", client, uri="file:///a")
        _add_resource(proxy, "srv1", "srv1__r2", client, uri="file:///b")

        await proxy._on_server_disconnected("srv1")

        assert proxy.resource_to_server["srv1__r1"].client is None
        assert proxy.resource_to_server["srv1__r2"].client is None


class TestDisconnectDoesNotAffectOtherServers:
    """Only the disconnected server's mappings should be cleared."""

    @pytest.mark.asyncio
    async def test_other_server_prompts_unaffected(self):
        proxy = _make_proxy()
        c1, c2 = _make_mock_client(), _make_mock_client()
        _add_prompt(proxy, "srv1", "srv1__p", c1)
        _add_prompt(proxy, "srv2", "srv2__p", c2)

        await proxy._on_server_disconnected("srv1")

        assert proxy.prompt_to_server["srv1__p"].client is None
        assert proxy.prompt_to_server["srv2__p"].client is c2

    @pytest.mark.asyncio
    async def test_other_server_resources_unaffected(self):
        proxy = _make_proxy()
        c1, c2 = _make_mock_client(), _make_mock_client()
        _add_resource(proxy, "srv1", "srv1__r", c1, uri="file:///a")
        _add_resource(proxy, "srv2", "srv2__r", c2, uri="file:///b")

        await proxy._on_server_disconnected("srv1")

        assert proxy.resource_to_server["srv1__r"].client is None
        assert proxy.resource_to_server["srv2__r"].client is c2

    @pytest.mark.asyncio
    async def test_other_server_tools_unaffected(self):
        proxy = _make_proxy()
        c1, c2 = _make_mock_client(), _make_mock_client()
        _add_tool(proxy, "srv1", "srv1__t", c1)
        _add_tool(proxy, "srv2", "srv2__t", c2)

        await proxy._on_server_disconnected("srv1")

        assert proxy.tool_to_server["srv1__t"].client is None
        assert proxy.tool_to_server["srv2__t"].client is c2


class TestDisconnectNotifications:
    """Disconnect should send list_changed notifications for all three types."""

    @pytest.mark.asyncio
    async def test_sends_all_notifications(self):
        proxy = _make_proxy()
        client = _make_mock_client()
        _add_tool(proxy, "srv1", "srv1__t", client)
        _add_prompt(proxy, "srv1", "srv1__p", client)
        _add_resource(proxy, "srv1", "srv1__r", client)

        # Mock the notification helpers
        proxy._send_tools_list_changed = AsyncMock()
        proxy._send_prompts_list_changed = AsyncMock()
        proxy._send_resources_list_changed = AsyncMock()

        await proxy._on_server_disconnected("srv1")

        proxy._send_tools_list_changed.assert_awaited_once()
        proxy._send_prompts_list_changed.assert_awaited_once()
        proxy._send_resources_list_changed.assert_awaited_once()


# ---------------------------------------------------------------------------
# Ghost mapping tests (unregister after disconnect)
# ---------------------------------------------------------------------------


class TestUnregisterAfterDisconnectRemovesGhosts:
    """Ghost tool/prompt/resource bug: unregister must remove mappings
    even after disconnect sets client=None."""

    @pytest.mark.asyncio
    async def test_ghost_tools_removed(self):
        """Disconnect sets client=None; unregister should STILL remove tools."""
        proxy = _make_proxy()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        _add_tool(proxy, "srvA", "srvA__tool1", c1)
        _add_tool(proxy, "srvB", "srvB__tool2", c2)
        proxy.client_manager.clients["srvA"] = c1
        proxy.client_manager.clients["srvB"] = c2

        await proxy._on_server_disconnected("srvA")
        assert proxy.tool_to_server["srvA__tool1"].client is None

        await proxy.unregister_client("srvA")
        assert "srvA__tool1" not in proxy.tool_to_server
        assert "srvB__tool2" in proxy.tool_to_server

    @pytest.mark.asyncio
    async def test_ghost_prompts_removed(self):
        """After disconnect + unregister, prompts should not persist."""
        proxy = _make_proxy()
        c1 = _make_mock_client()
        _add_prompt(proxy, "srvA", "srvA__p1", c1)
        proxy.client_manager.clients["srvA"] = c1

        await proxy._on_server_disconnected("srvA")
        await proxy.unregister_client("srvA")
        assert "srvA__p1" not in proxy.prompt_to_server

    @pytest.mark.asyncio
    async def test_ghost_resources_removed(self):
        """After disconnect + unregister, resources should not persist."""
        proxy = _make_proxy()
        c1 = _make_mock_client()
        _add_resource(proxy, "srvA", "srvA__r1", c1, "res://x")
        proxy.client_manager.clients["srvA"] = c1

        await proxy._on_server_disconnected("srvA")
        await proxy.unregister_client("srvA")
        assert "srvA__r1" not in proxy.resource_to_server
