"""Tests for prompt and resource subsystems in MCPProxyServer.

Covers: _list_prompts, _get_prompt, _list_resources, _read_resource,
        _subscribe_resource, _unsubscribe_resource, and error paths.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp import types

from src.multimcp.mcp_proxy import MCPProxyServer, PromptMapping, ResourceMapping


def _make_proxy():
    """Create a minimal MCPProxyServer bypassing __init__ for unit testing."""
    proxy = MCPProxyServer.__new__(MCPProxyServer)
    proxy.tool_to_server = {}
    proxy.prompt_to_server = {}
    proxy.resource_to_server = {}
    proxy._resource_objects = {}
    proxy.client_manager = MagicMock()
    proxy.trigger_manager = MagicMock()
    proxy.audit_logger = MagicMock()
    proxy.logger = MagicMock()
    proxy._register_lock = MagicMock()
    proxy._register_lock.__aenter__ = AsyncMock()
    proxy._register_lock.__aexit__ = AsyncMock()
    proxy.retrieval_pipeline = None
    proxy._server_session = None
    proxy.capabilities = {}
    return proxy


def _make_prompt(name: str, description: str = "test prompt") -> types.Prompt:
    return types.Prompt(name=name, description=description)


def _make_resource(name: str, uri: str) -> types.Resource:
    return types.Resource(name=name, uri=uri)


# ── Prompt tests ──────────────────────────────────────────────────────


class TestListPrompts:
    @pytest.mark.asyncio
    async def test_returns_all_prompts_namespaced(self):
        proxy = _make_proxy()
        client = AsyncMock()
        proxy.prompt_to_server["github__summarize"] = PromptMapping(
            server_name="github", client=client,
            prompt=_make_prompt("summarize"),
        )
        proxy.prompt_to_server["slack__notify"] = PromptMapping(
            server_name="slack", client=client,
            prompt=_make_prompt("notify"),
        )
        result = await proxy._list_prompts(None)
        names = [p.name for p in result.root.prompts]
        assert sorted(names) == ["github__summarize", "slack__notify"]

    @pytest.mark.asyncio
    async def test_empty_when_no_prompts(self):
        proxy = _make_proxy()
        result = await proxy._list_prompts(None)
        assert result.root.prompts == []


class TestGetPrompt:
    @pytest.mark.asyncio
    async def test_routes_to_correct_backend(self):
        proxy = _make_proxy()
        client = AsyncMock()
        expected_result = types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text="hello"),
                )
            ],
        )
        client.get_prompt = AsyncMock(return_value=expected_result)
        proxy.prompt_to_server["github__summarize"] = PromptMapping(
            server_name="github", client=client,
            prompt=_make_prompt("summarize"),
        )
        req = MagicMock()
        req.params.name = "github__summarize"
        req.params.arguments = {"repo": "test"}
        result = await proxy._get_prompt(req)
        # Verify backend was called with original (un-namespaced) name
        client.get_prompt.assert_called_once_with("summarize", {"repo": "test"})

    @pytest.mark.asyncio
    async def test_unknown_prompt_returns_error(self):
        proxy = _make_proxy()
        req = MagicMock()
        req.params.name = "nonexistent__prompt"
        result = await proxy._get_prompt(req)
        assert result.root.isError is True

    @pytest.mark.asyncio
    async def test_backend_failure_returns_error(self):
        proxy = _make_proxy()
        client = AsyncMock()
        client.get_prompt = AsyncMock(side_effect=RuntimeError("connection lost"))
        proxy.prompt_to_server["github__summarize"] = PromptMapping(
            server_name="github", client=client,
            prompt=_make_prompt("summarize"),
        )
        req = MagicMock()
        req.params.name = "github__summarize"
        req.params.arguments = {}
        result = await proxy._get_prompt(req)
        assert result.root.isError is True

    @pytest.mark.asyncio
    async def test_prompt_with_none_client_returns_error(self):
        proxy = _make_proxy()
        proxy.prompt_to_server["github__summarize"] = PromptMapping(
            server_name="github", client=None,
            prompt=_make_prompt("summarize"),
        )
        req = MagicMock()
        req.params.name = "github__summarize"
        req.params.arguments = {}
        result = await proxy._get_prompt(req)
        assert result.root.isError is True


# ── Resource tests ────────────────────────────────────────────────────


class TestListResources:
    @pytest.mark.asyncio
    async def test_returns_resources_with_namespaced_name_raw_uri(self):
        proxy = _make_proxy()
        client = AsyncMock()
        proxy.resource_to_server["file:///data.csv"] = ResourceMapping(
            server_name="filesystem", client=client,
            resource=_make_resource("data.csv", "file:///data.csv"),
        )
        result = await proxy._list_resources(None)
        resources = result.root.resources
        assert len(resources) == 1
        # Name should be namespaced
        assert resources[0].name == "filesystem__data.csv"
        # URI must remain raw (not namespaced)
        assert str(resources[0].uri) == "file:///data.csv"

    @pytest.mark.asyncio
    async def test_empty_when_no_resources(self):
        proxy = _make_proxy()
        result = await proxy._list_resources(None)
        assert result.root.resources == []

    @pytest.mark.asyncio
    async def test_multiple_servers_resources(self):
        proxy = _make_proxy()
        client = AsyncMock()
        proxy.resource_to_server["file:///a.txt"] = ResourceMapping(
            server_name="fs1", client=client,
            resource=_make_resource("a.txt", "file:///a.txt"),
        )
        proxy.resource_to_server["https://api.example.com/data"] = ResourceMapping(
            server_name="api", client=client,
            resource=_make_resource("data", "https://api.example.com/data"),
        )
        result = await proxy._list_resources(None)
        names = sorted([r.name for r in result.root.resources])
        assert names == ["api__data", "fs1__a.txt"]


class TestReadResource:
    @pytest.mark.asyncio
    async def test_routes_with_raw_uri(self):
        proxy = _make_proxy()
        client = AsyncMock()
        read_result = MagicMock()
        client.read_resource = AsyncMock(return_value=read_result)
        proxy.resource_to_server["file:///data.csv"] = ResourceMapping(
            server_name="fs", client=client,
            resource=_make_resource("data.csv", "file:///data.csv"),
        )
        req = MagicMock()
        req.params.uri = "file:///data.csv"
        await proxy._read_resource(req)
        # Backend receives the raw URI, not a namespaced one
        client.read_resource.assert_called_once_with("file:///data.csv")

    @pytest.mark.asyncio
    async def test_unknown_resource_returns_error(self):
        proxy = _make_proxy()
        req = MagicMock()
        req.params.uri = "file:///nonexistent"
        result = await proxy._read_resource(req)
        assert result.root.isError is True

    @pytest.mark.asyncio
    async def test_backend_failure_returns_error(self):
        proxy = _make_proxy()
        client = AsyncMock()
        client.read_resource = AsyncMock(side_effect=RuntimeError("timeout"))
        proxy.resource_to_server["file:///data.csv"] = ResourceMapping(
            server_name="fs", client=client,
            resource=_make_resource("data.csv", "file:///data.csv"),
        )
        req = MagicMock()
        req.params.uri = "file:///data.csv"
        result = await proxy._read_resource(req)
        assert result.root.isError is True


# ── Subscribe / Unsubscribe tests ────────────────────────────────────


class TestSubscribeResource:
    @pytest.mark.asyncio
    async def test_passes_raw_uri_to_backend(self):
        proxy = _make_proxy()
        client = AsyncMock()
        client.subscribe_resource = AsyncMock()
        proxy.resource_to_server["file:///watch.log"] = ResourceMapping(
            server_name="fs", client=client,
            resource=_make_resource("watch.log", "file:///watch.log"),
        )
        req = MagicMock()
        req.params.uri = "file:///watch.log"
        result = await proxy._subscribe_resource(req)
        # Raw URI passed to backend — NOT namespaced
        client.subscribe_resource.assert_called_once_with("file:///watch.log")
        assert not hasattr(result.root, "isError") or result.root.isError is not True

    @pytest.mark.asyncio
    async def test_unknown_resource_returns_error(self):
        proxy = _make_proxy()
        req = MagicMock()
        req.params.uri = "file:///nonexistent"
        result = await proxy._subscribe_resource(req)
        assert result.root.isError is True

    @pytest.mark.asyncio
    async def test_backend_failure_returns_error(self):
        proxy = _make_proxy()
        client = AsyncMock()
        client.subscribe_resource = AsyncMock(
            side_effect=RuntimeError("subscribe failed")
        )
        proxy.resource_to_server["file:///watch.log"] = ResourceMapping(
            server_name="fs", client=client,
            resource=_make_resource("watch.log", "file:///watch.log"),
        )
        req = MagicMock()
        req.params.uri = "file:///watch.log"
        result = await proxy._subscribe_resource(req)
        assert result.root.isError is True


class TestUnsubscribeResource:
    @pytest.mark.asyncio
    async def test_passes_raw_uri_to_backend(self):
        proxy = _make_proxy()
        client = AsyncMock()
        client.unsubscribe_resource = AsyncMock()
        proxy.resource_to_server["file:///watch.log"] = ResourceMapping(
            server_name="fs", client=client,
            resource=_make_resource("watch.log", "file:///watch.log"),
        )
        req = MagicMock()
        req.params.uri = "file:///watch.log"
        result = await proxy._unsubscribe_resource(req)
        client.unsubscribe_resource.assert_called_once_with("file:///watch.log")
        assert not hasattr(result.root, "isError") or result.root.isError is not True

    @pytest.mark.asyncio
    async def test_unknown_resource_returns_error(self):
        proxy = _make_proxy()
        req = MagicMock()
        req.params.uri = "file:///nonexistent"
        result = await proxy._unsubscribe_resource(req)
        assert result.root.isError is True

    @pytest.mark.asyncio
    async def test_none_client_returns_error(self):
        proxy = _make_proxy()
        proxy.resource_to_server["file:///watch.log"] = ResourceMapping(
            server_name="fs", client=None,
            resource=_make_resource("watch.log", "file:///watch.log"),
        )
        req = MagicMock()
        req.params.uri = "file:///watch.log"
        result = await proxy._unsubscribe_resource(req)
        assert result.root.isError is True
