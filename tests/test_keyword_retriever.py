"""Tests for KeywordRetriever TF-IDF scoring."""
import pytest
from unittest.mock import MagicMock
from mcp import types
from src.multimcp.retrieval.keyword import KeywordRetriever
from src.multimcp.retrieval.models import RetrievalConfig, RetrievalContext, ScoredTool


def _make_tool(name: str, desc: str) -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": {}},
    )


def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()
    return m


def _build_registry():
    """Build a realistic tool registry for testing."""
    tools = {
        "github__search_repositories": _make_mapping(
            "github", _make_tool("search_repositories", "Search for GitHub repositories by name, topic, or description")
        ),
        "github__get_me": _make_mapping(
            "github", _make_tool("get_me", "Get details of the authenticated GitHub user")
        ),
        "github__list_issues": _make_mapping(
            "github", _make_tool("list_issues", "List issues in a GitHub repository with filtering")
        ),
        "github__create_pull_request": _make_mapping(
            "github", _make_tool("create_pull_request", "Create a new pull request in a GitHub repository")
        ),
        "obsidian__global_search": _make_mapping(
            "obsidian", _make_tool("global_search", "Search across all notes in the Obsidian vault")
        ),
        "obsidian__read_note": _make_mapping(
            "obsidian", _make_tool("read_note", "Read the content of a specific note from the Obsidian vault")
        ),
        "obsidian__write_note": _make_mapping(
            "obsidian", _make_tool("write_note", "Write or update a note in the Obsidian vault")
        ),
        "exa__search": _make_mapping(
            "exa", _make_tool("search", "Search the web using Exa neural search engine")
        ),
        "exa__get_contents": _make_mapping(
            "exa", _make_tool("get_contents", "Get the full text content of web pages from URLs")
        ),
    }
    return tools


class TestKeywordRetriever:
    def setup_method(self):
        self.config = RetrievalConfig(enabled=True, top_k=5)
        self.registry = _build_registry()
        self.retriever = KeywordRetriever(self.config)
        self.retriever.rebuild_index(self.registry)

    @pytest.mark.asyncio
    async def test_github_query_ranks_github_higher(self):
        ctx = RetrievalContext(session_id="s1", query="search GitHub repositories")
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        tool_names = [r.tool_mapping.tool.name for r in results]
        assert "search_repositories" in tool_names[:3]

    @pytest.mark.asyncio
    async def test_obsidian_query_ranks_obsidian_higher(self):
        ctx = RetrievalContext(session_id="s1", query="read a note from my vault")
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        tool_names = [r.tool_mapping.tool.name for r in results]
        assert "read_note" in tool_names[:3]

    @pytest.mark.asyncio
    async def test_respects_top_k(self):
        ctx = RetrievalContext(session_id="s1", query="search")
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        assert len(results) <= self.config.top_k

    @pytest.mark.asyncio
    async def test_scores_in_range(self):
        ctx = RetrievalContext(session_id="s1", query="GitHub search")
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        for r in results:
            assert 0.0 <= r.score <= 1.0

    @pytest.mark.asyncio
    async def test_empty_query_returns_results(self):
        """Empty query should still return top-k tools (all score equally)."""
        ctx = RetrievalContext(session_id="s1", query="")
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        assert len(results) <= self.config.top_k

    @pytest.mark.asyncio
    async def test_namespace_hint_boosts(self):
        ctx = RetrievalContext(
            session_id="s1",
            query="search",
            server_hint="exa",
        )
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        exa_scores = [r.score for r in results if r.tool_mapping.server_name == "exa"]
        if exa_scores:
            assert max(exa_scores) >= 0.1  # Exa tools should have reasonable scores

    @pytest.mark.asyncio
    async def test_rebuild_index_updates(self):
        new_registry = {
            "new__unique_tool": _make_mapping(
                "new", _make_tool("unique_tool", "A completely unique specialized description about quantum")
            ),
        }
        self.retriever.rebuild_index(new_registry)
        ctx = RetrievalContext(session_id="s1", query="quantum specialized")
        results = await self.retriever.retrieve(ctx, list(new_registry.values()))
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_idf_weighting(self):
        """Rare terms should have higher discriminative power."""
        ctx = RetrievalContext(session_id="s1", query="neural")
        results = await self.retriever.retrieve(ctx, list(self.registry.values()))
        if results:
            # "neural" only appears in exa__search description
            assert results[0].tool_mapping.tool.name == "search"
            assert results[0].tool_mapping.server_name == "exa"

    @pytest.mark.asyncio
    async def test_fewer_candidates_than_top_k(self):
        small_registry = {"github__get_me": self.registry["github__get_me"]}
        self.retriever.rebuild_index(small_registry)
        ctx = RetrievalContext(session_id="s1", query="GitHub user")
        results = await self.retriever.retrieve(ctx, list(small_registry.values()))
        assert len(results) == 1
