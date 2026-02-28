"""Tests for resource operations: subscribe, unsubscribe, read, list.

Resource keys use RAW URIs (not namespaced) because Pydantic's AnyUrl
rejects namespaced URI strings. The proxy passes raw URIs directly to
backends without _split_key() — unlike tools/prompts which are namespaced.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp import types

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, ResourceMapping


def _make_proxy_with_resource():
    """Create a proxy with a resource stored using raw URI key (matches real behavior)."""
    manager = MCPClientManager()
    proxy = MCPProxyServer(manager)
    mock_client = AsyncMock()
    mock_resource = MagicMock(spec=types.Resource)
    mock_resource.uri = "resource://weather/data"
    mock_resource.name = "Weather Data"
    copied = MagicMock(spec=types.Resource)
    copied.uri = "resource://weather/data"
    copied.name = "Weather Data"
    mock_resource.model_copy = MagicMock(return_value=copied)

    # Real behavior: initialize_single_client stores with raw URI as key
    proxy.resource_to_server["resource://weather/data"] = ResourceMapping(
        server_name="weather", client=mock_client, resource=mock_resource
    )
    return proxy, mock_client


class TestSubscribeResource:
    """Subscribe passes raw URI directly to backend (no namespace stripping needed)."""

    @pytest.mark.asyncio
    async def test_subscribe_forwards_raw_uri(self):
        proxy, mock_client = _make_proxy_with_resource()
        mock_client.subscribe_resource = AsyncMock()

        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://weather/data"

        await proxy._subscribe_resource(req)

        mock_client.subscribe_resource.assert_called_once()
        call_arg = mock_client.subscribe_resource.call_args[0][0]
        assert str(call_arg) == "resource://weather/data"

    @pytest.mark.asyncio
    async def test_subscribe_unknown_resource_returns_error(self):
        proxy, _ = _make_proxy_with_resource()
        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://nonexistent/foo"

        result = await proxy._subscribe_resource(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_subscribe_disconnected_client_returns_error(self):
        proxy, _ = _make_proxy_with_resource()
        proxy.resource_to_server["resource://weather/data"].client = None

        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://weather/data"

        result = await proxy._subscribe_resource(req)
        assert result.root.isError


class TestUnsubscribeResource:
    """Unsubscribe passes raw URI directly to backend."""

    @pytest.mark.asyncio
    async def test_unsubscribe_forwards_raw_uri(self):
        proxy, mock_client = _make_proxy_with_resource()
        mock_client.unsubscribe_resource = AsyncMock()

        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://weather/data"

        await proxy._unsubscribe_resource(req)

        mock_client.unsubscribe_resource.assert_called_once()
        call_arg = mock_client.unsubscribe_resource.call_args[0][0]
        assert str(call_arg) == "resource://weather/data"

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_resource_returns_error(self):
        proxy, _ = _make_proxy_with_resource()
        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://nonexistent/foo"

        result = await proxy._unsubscribe_resource(req)
        assert result.root.isError


class TestReadResource:
    """Read resource forwards raw URI to backend."""

    @pytest.mark.asyncio
    async def test_read_forwards_raw_uri(self):
        proxy, mock_client = _make_proxy_with_resource()
        mock_client.read_resource = AsyncMock(return_value=MagicMock(
            contents=[MagicMock(uri="resource://weather/data", text="sunny")]
        ))

        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://weather/data"

        await proxy._read_resource(req)

        mock_client.read_resource.assert_called_once()
        call_arg = mock_client.read_resource.call_args[0][0]
        assert str(call_arg) == "resource://weather/data"

    @pytest.mark.asyncio
    async def test_read_disconnected_client_returns_error(self):
        proxy, _ = _make_proxy_with_resource()
        proxy.resource_to_server["resource://weather/data"].client = None

        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://weather/data"

        result = await proxy._read_resource(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_read_unknown_resource_returns_error(self):
        proxy, _ = _make_proxy_with_resource()
        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://nonexistent/foo"

        result = await proxy._read_resource(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_read_client_exception_returns_error(self):
        proxy, mock_client = _make_proxy_with_resource()
        mock_client.read_resource = AsyncMock(side_effect=Exception("connection lost"))

        req = MagicMock()
        req.params = MagicMock()
        req.params.uri = "resource://weather/data"

        result = await proxy._read_resource(req)
        assert result.root.isError


class TestListResources:
    """List resources returns entries with namespaced name but raw URI."""

    @pytest.mark.asyncio
    async def test_list_returns_namespaced_name(self):
        proxy, _ = _make_proxy_with_resource()
        result = await proxy._list_resources(MagicMock())
        resources = result.root.resources
        assert len(resources) == 1
        # Name should be namespaced for disambiguation
        assert resources[0].name == "weather__Weather Data"

    @pytest.mark.asyncio
    async def test_list_preserves_original_uri(self):
        proxy, _ = _make_proxy_with_resource()
        result = await proxy._list_resources(MagicMock())
        resources = result.root.resources
        # URI stays raw — client uses it for read/subscribe calls
        assert str(resources[0].uri) == "resource://weather/data"

    @pytest.mark.asyncio
    async def test_resource_mapping_type_consistency(self):
        proxy, _ = _make_proxy_with_resource()
        for key, value in proxy.resource_to_server.items():
            assert isinstance(value, ResourceMapping), (
                f"resource_to_server[{key}] is {type(value).__name__}, expected ResourceMapping"
            )

    @pytest.mark.asyncio
    async def test_empty_resource_list(self):
        manager = MCPClientManager()
        proxy = MCPProxyServer(manager)
        result = await proxy._list_resources(MagicMock())
        assert result.root.resources == []

    @pytest.mark.asyncio
    async def test_multiple_servers_resources_listed(self):
        proxy, mock_client = _make_proxy_with_resource()
        mock_resource2 = MagicMock(spec=types.Resource)
        mock_resource2.uri = "resource://news/headlines"
        mock_resource2.name = "Headlines"
        copied2 = MagicMock(spec=types.Resource)
        copied2.uri = "resource://news/headlines"
        copied2.name = "Headlines"
        mock_resource2.model_copy = MagicMock(return_value=copied2)
        proxy.resource_to_server["resource://news/headlines"] = ResourceMapping(
            server_name="news", client=AsyncMock(), resource=mock_resource2
        )
        result = await proxy._list_resources(MagicMock())
        assert len(result.root.resources) == 2
