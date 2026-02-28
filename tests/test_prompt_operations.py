"""Comprehensive tests for prompt operations: get_prompt, complete, list_prompts.

All prompt operations use namespaced keys (server__promptname). The proxy
calls _split_key() to recover the original name before forwarding to backends.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from mcp import types

from src.multimcp.mcp_client import MCPClientManager
from src.multimcp.mcp_proxy import MCPProxyServer, PromptMapping


def _make_proxy_with_prompt():
    """Create a proxy with a single namespaced prompt mapping."""
    manager = MCPClientManager()
    proxy = MCPProxyServer(manager)
    mock_client = AsyncMock()

    mock_prompt = MagicMock(spec=types.Prompt)
    mock_prompt.name = "summarize"
    mock_prompt.description = "Summarize text"
    mock_prompt.arguments = []

    copied_prompt = MagicMock(spec=types.Prompt)
    copied_prompt.name = "summarize"
    copied_prompt.description = "Summarize text"
    copied_prompt.arguments = []
    mock_prompt.model_copy = MagicMock(return_value=copied_prompt)

    proxy.prompt_to_server["weather__summarize"] = PromptMapping(
        server_name="weather", client=mock_client, prompt=mock_prompt
    )
    return proxy, mock_client


class TestGetPrompt:
    """_get_prompt should route to the correct backend with the original name."""

    @pytest.mark.asyncio
    async def test_get_prompt_strips_namespace(self):
        proxy, mock_client = _make_proxy_with_prompt()
        mock_client.get_prompt = AsyncMock(return_value=MagicMock(
            messages=[MagicMock()], description="summary"
        ))

        req = MagicMock()
        req.params = MagicMock()
        req.params.name = "weather__summarize"
        req.params.arguments = {"text": "hello world"}

        result = await proxy._get_prompt(req)

        # Backend receives original name, not namespaced
        mock_client.get_prompt.assert_called_once_with(
            "summarize", {"text": "hello world"}
        )

    @pytest.mark.asyncio
    async def test_get_prompt_returns_server_result(self):
        proxy, mock_client = _make_proxy_with_prompt()
        mock_response = MagicMock(
            messages=[MagicMock()], description="result"
        )
        mock_client.get_prompt = AsyncMock(return_value=mock_response)

        req = MagicMock()
        req.params = MagicMock()
        req.params.name = "weather__summarize"
        req.params.arguments = {}

        result = await proxy._get_prompt(req)
        assert isinstance(result, types.ServerResult)

    @pytest.mark.asyncio
    async def test_get_prompt_unknown_returns_error(self):
        proxy, _ = _make_proxy_with_prompt()
        req = MagicMock()
        req.params = MagicMock()
        req.params.name = "nonexistent__foo"
        req.params.arguments = {}

        result = await proxy._get_prompt(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_get_prompt_disconnected_client_returns_error(self):
        proxy, _ = _make_proxy_with_prompt()
        proxy.prompt_to_server["weather__summarize"].client = None

        req = MagicMock()
        req.params = MagicMock()
        req.params.name = "weather__summarize"
        req.params.arguments = {}

        result = await proxy._get_prompt(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_get_prompt_backend_exception_returns_error(self):
        proxy, mock_client = _make_proxy_with_prompt()
        mock_client.get_prompt = AsyncMock(side_effect=Exception("timeout"))

        req = MagicMock()
        req.params = MagicMock()
        req.params.name = "weather__summarize"
        req.params.arguments = {}

        result = await proxy._get_prompt(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_get_prompt_with_none_arguments(self):
        """get_prompt should handle None arguments gracefully."""
        proxy, mock_client = _make_proxy_with_prompt()
        mock_client.get_prompt = AsyncMock(return_value=MagicMock(
            messages=[], description="empty"
        ))

        req = MagicMock()
        req.params = MagicMock()
        req.params.name = "weather__summarize"
        req.params.arguments = None

        result = await proxy._get_prompt(req)
        mock_client.get_prompt.assert_called_once_with("summarize", None)


class TestComplete:
    """_complete should route to correct backend with stripped ref name."""

    @pytest.mark.asyncio
    async def test_complete_strips_namespace_from_ref(self):
        proxy, mock_client = _make_proxy_with_prompt()
        # Return a proper CompleteResult to avoid Pydantic validation error
        mock_client.complete = AsyncMock(return_value=types.CompleteResult(
            completion=types.Completion(values=["result"], hasMore=False, total=1)
        ))

        ref = MagicMock()
        ref.name = "weather__summarize"
        ref.type = "ref/prompt"
        stripped_ref = MagicMock()
        stripped_ref.name = "summarize"
        ref.model_copy = MagicMock(return_value=stripped_ref)

        req = MagicMock()
        req.params = MagicMock()
        req.params.ref = ref
        req.params.argument = MagicMock(name="arg", value="val")

        await proxy._complete(req)
        # Verify model_copy was called to strip the namespace
        ref.model_copy.assert_called_once_with(update={"name": "summarize"})
        mock_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_unknown_prompt_returns_error(self):
        proxy, _ = _make_proxy_with_prompt()

        ref = MagicMock()
        ref.name = "nonexistent__foo"
        ref.type = "ref/prompt"

        req = MagicMock()
        req.params = MagicMock()
        req.params.ref = ref
        req.params.argument = MagicMock()

        result = await proxy._complete(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_complete_disconnected_client_returns_error(self):
        proxy, _ = _make_proxy_with_prompt()
        proxy.prompt_to_server["weather__summarize"].client = None

        ref = MagicMock()
        ref.name = "weather__summarize"
        ref.type = "ref/prompt"

        req = MagicMock()
        req.params = MagicMock()
        req.params.ref = ref
        req.params.argument = MagicMock()

        result = await proxy._complete(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_complete_backend_exception_returns_error(self):
        proxy, mock_client = _make_proxy_with_prompt()
        mock_client.complete = AsyncMock(side_effect=Exception("backend down"))

        ref = MagicMock()
        ref.name = "weather__summarize"
        ref.type = "ref/prompt"
        ref.model_copy = MagicMock(return_value=MagicMock())

        req = MagicMock()
        req.params = MagicMock()
        req.params.ref = ref
        req.params.argument = MagicMock()

        result = await proxy._complete(req)
        assert result.root.isError

    @pytest.mark.asyncio
    async def test_complete_ref_without_name_returns_error(self):
        """If ref has no name attribute, _complete should return error."""
        proxy, _ = _make_proxy_with_prompt()

        ref = MagicMock(spec=[])  # No attributes
        req = MagicMock()
        req.params = MagicMock()
        req.params.ref = ref
        req.params.argument = MagicMock()

        result = await proxy._complete(req)
        assert result.root.isError


class TestListPrompts:
    """_list_prompts should return all cached prompts with namespaced names."""

    @pytest.mark.asyncio
    async def test_list_returns_namespaced_names(self):
        proxy, _ = _make_proxy_with_prompt()
        result = await proxy._list_prompts(MagicMock())
        prompts = result.root.prompts
        assert len(prompts) == 1
        assert prompts[0].name == "weather__summarize"

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty(self):
        manager = MCPClientManager()
        proxy = MCPProxyServer(manager)
        result = await proxy._list_prompts(MagicMock())
        assert result.root.prompts == []

    @pytest.mark.asyncio
    async def test_list_multiple_servers(self):
        proxy, mock_client = _make_proxy_with_prompt()

        mock_prompt2 = MagicMock(spec=types.Prompt)
        mock_prompt2.name = "analyze"
        copied2 = MagicMock(spec=types.Prompt)
        copied2.name = "analyze"
        mock_prompt2.model_copy = MagicMock(return_value=copied2)

        proxy.prompt_to_server["news__analyze"] = PromptMapping(
            server_name="news", client=AsyncMock(), prompt=mock_prompt2
        )
        result = await proxy._list_prompts(MagicMock())
        assert len(result.root.prompts) == 2
        names = {p.name for p in result.root.prompts}
        assert "weather__summarize" in names
        assert "news__analyze" in names

    @pytest.mark.asyncio
    async def test_prompt_mapping_type_consistency(self):
        proxy, _ = _make_proxy_with_prompt()
        for key, value in proxy.prompt_to_server.items():
            assert isinstance(value, PromptMapping), (
                f"prompt_to_server[{key}] is {type(value).__name__}, expected PromptMapping"
            )
