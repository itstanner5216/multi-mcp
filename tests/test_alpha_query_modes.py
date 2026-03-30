"""Tests for BMXFRetriever dual-index query modes — 07-01-PLAN.md mandatory tests.

Covers:
- context.query_mode == "env" uses _env_index (alpha_override=0.5)
- context.query_mode == "nl" uses _nl_index (alpha_override=None)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from mcp import types

from src.multimcp.retrieval.bmx_retriever import BMXFRetriever
from src.multimcp.retrieval.models import RetrievalConfig, RetrievalContext, ScoredTool


def _make_mapping(server: str, name: str):
    m = MagicMock()
    m.server_name = server
    m.tool = types.Tool(
        name=name,
        description="A tool",
        inputSchema={"type": "object", "properties": {}},
    )
    m.client = MagicMock()
    return m


def _build_retriever_with_index() -> BMXFRetriever:
    """Build a BMXFRetriever with a real registry to populate both indexes."""
    from src.multimcp.mcp_proxy import ToolMapping

    config = RetrievalConfig(shadow_mode=False, max_k=10)
    retriever = BMXFRetriever(config=config)

    registry = {
        f"github__tool{i}": _make_mapping("github", f"tool{i}")
        for i in range(5)
    }
    retriever.rebuild_index(registry)
    return retriever


class TestEnvUsesEnvIndex:
    @pytest.mark.asyncio
    async def test_env_uses_env_index(self):
        """context.query_mode='env' must use _env_index (alpha_override=0.5)."""
        retriever = _build_retriever_with_index()

        assert retriever._env_index is not None
        assert retriever._nl_index is not None
        assert retriever._env_index.alpha_override == 0.5
        assert retriever._nl_index.alpha_override is None

        # Verify retrieve() selects _env_index for "env" mode
        with patch.object(
            retriever._env_index, "search_fields", wraps=retriever._env_index.search_fields
        ) as mock_env_search, patch.object(
            retriever._nl_index, "search_fields", wraps=retriever._nl_index.search_fields
        ) as mock_nl_search:
            ctx = RetrievalContext(
                session_id="s1",
                query="search repository",
                query_mode="env",
            )
            candidates = [_make_mapping("github", f"tool{i}") for i in range(5)]
            await retriever.retrieve(ctx, candidates)

            mock_env_search.assert_called_once()
            mock_nl_search.assert_not_called()

    def test_env_index_alpha_override(self):
        """_env_index.alpha_override must be 0.5."""
        retriever = _build_retriever_with_index()
        assert retriever._env_index is not None
        assert retriever._env_index.alpha_override == 0.5


class TestNlUsesNlIndex:
    @pytest.mark.asyncio
    async def test_nl_uses_nl_index(self):
        """context.query_mode='nl' must use _nl_index (alpha_override=None)."""
        retriever = _build_retriever_with_index()

        with patch.object(
            retriever._env_index, "search_fields", wraps=retriever._env_index.search_fields
        ) as mock_env_search, patch.object(
            retriever._nl_index, "search_fields", wraps=retriever._nl_index.search_fields
        ) as mock_nl_search:
            ctx = RetrievalContext(
                session_id="s1",
                query="list files in directory",
                query_mode="nl",
            )
            candidates = [_make_mapping("github", f"tool{i}") for i in range(5)]
            await retriever.retrieve(ctx, candidates)

            mock_nl_search.assert_called_once()
            mock_env_search.assert_not_called()

    def test_nl_index_alpha_override_none(self):
        """_nl_index.alpha_override must be None (auto-tune)."""
        retriever = _build_retriever_with_index()
        assert retriever._nl_index is not None
        assert retriever._nl_index.alpha_override is None

    @pytest.mark.asyncio
    async def test_default_mode_is_env(self):
        """RetrievalContext default query_mode is 'env'."""
        ctx = RetrievalContext(session_id="s", query="search files")
        assert ctx.query_mode == "env"
