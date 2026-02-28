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
