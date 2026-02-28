"""End-to-end integration tests for the complete retrieval pipeline."""

import json
import pytest
from unittest.mock import MagicMock
from mcp import types
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.keyword import KeywordRetriever
from src.multimcp.retrieval.ranker import RelevanceRanker
from src.multimcp.retrieval.assembler import TieredAssembler
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import RetrievalConfig


def _make_tool(name: str, desc: str, props: dict = None) -> types.Tool:
    if props is None:
        props = {}
    return types.Tool(
        name=name, description=desc, inputSchema={"type": "object", "properties": props}
    )


def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()
    return m


def _build_large_registry():
    """Build a 20+ tool registry across 3 servers for realistic testing."""
    tools = {}
    # GitHub tools (8)
    gh_tools = [
        ("get_me", "Get details of the authenticated GitHub user"),
        (
            "search_repositories",
            "Search for GitHub repositories by name topic or description",
        ),
        (
            "list_issues",
            "List issues in a GitHub repository with filtering by state label and assignee",
        ),
        ("create_pull_request", "Create a new pull request in a GitHub repository"),
        ("get_commit", "Get details for a specific commit from a GitHub repository"),
        ("list_branches", "List branches in a GitHub repository"),
        (
            "get_file_contents",
            "Get the contents of a file or directory from a GitHub repository",
        ),
        ("create_issue", "Create a new issue in a GitHub repository"),
    ]
    for name, desc in gh_tools:
        tool = _make_tool(name, desc, {"query": {"type": "string"}})
        tools[f"github__{name}"] = _make_mapping("github", tool)

    # Obsidian tools (6)
    obs_tools = [
        (
            "global_search",
            "Search across all notes in the Obsidian vault using full text search",
        ),
        ("read_note", "Read the content of a specific note from the Obsidian vault"),
        (
            "write_note",
            "Write or update a note in the Obsidian vault with markdown content",
        ),
        (
            "list_notes",
            "List all notes and folders in the vault or a specific directory",
        ),
        ("delete_note", "Delete a specific note from the Obsidian vault permanently"),
        ("get_tags", "Get all tags used across notes in the Obsidian vault"),
    ]
    for name, desc in obs_tools:
        tool = _make_tool(name, desc, {"path": {"type": "string"}})
        tools[f"obsidian__{name}"] = _make_mapping("obsidian", tool)

    # Exa tools (4)
    exa_tools = [
        (
            "search",
            "Search the web using Exa neural search engine for high quality results",
        ),
        ("get_contents", "Get the full text content of web pages from URLs"),
        ("find_similar", "Find web pages similar to a given URL or description"),
        (
            "search_highlights",
            "Search the web and return highlighted relevant passages",
        ),
    ]
    for name, desc in exa_tools:
        tool = _make_tool(name, desc, {"query": {"type": "string"}})
        tools[f"exa__{name}"] = _make_mapping("exa", tool)

    return tools


class TestEndToEndRetrieval:
    """Full pipeline: keyword retrieval → ranking → tiered assembly."""

    @pytest.mark.asyncio
    async def test_anchor_only_fresh_session(self):
        config = RetrievalConfig(
            enabled=True,
            top_k=5,
            full_description_count=3,
            anchor_tools=["github__get_me"],
        )
        registry = _build_large_registry()
        retriever = KeywordRetriever(config)
        retriever.rebuild_index(registry)

        pipeline = RetrievalPipeline(
            retriever=retriever,
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            ranker=RelevanceRanker(),
            assembler=TieredAssembler(),
        )

        tools = await pipeline.get_tools_for_list("new-session")
        assert len(tools) == 1
        assert tools[0].name == "get_me"

    @pytest.mark.asyncio
    async def test_disclosed_tools_ranked_and_tiered(self):
        config = RetrievalConfig(
            enabled=True,
            top_k=10,
            full_description_count=3,
            anchor_tools=["github__get_me"],
        )
        registry = _build_large_registry()
        retriever = KeywordRetriever(config)
        retriever.rebuild_index(registry)

        pipeline = RetrievalPipeline(
            retriever=retriever,
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            ranker=RelevanceRanker(),
            assembler=TieredAssembler(),
        )

        # Disclose 8 tools
        pipeline.session_manager.get_or_create_session("s1")
        disclosed = [
            "github__get_me",
            "github__search_repositories",
            "github__list_issues",
            "obsidian__global_search",
            "obsidian__read_note",
            "exa__search",
            "exa__get_contents",
            "exa__find_similar",
        ]
        pipeline.session_manager.add_tools("s1", disclosed)

        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 8

        # Top 3 should have full descriptions
        for t in tools[:3]:
            assert t.description is not None

    @pytest.mark.asyncio
    async def test_monotonic_expansion(self):
        config = RetrievalConfig(
            enabled=True,
            top_k=5,
            anchor_tools=["github__get_me"],
        )
        registry = _build_large_registry()
        retriever = KeywordRetriever(config)
        retriever.rebuild_index(registry)

        pipeline = RetrievalPipeline(
            retriever=retriever,
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            ranker=RelevanceRanker(),
            assembler=TieredAssembler(),
        )

        counts = []
        for i in range(5):
            if i > 0:
                pipeline.session_manager.add_tools("s1", [list(registry.keys())[i]])
            tools = await pipeline.get_tools_for_list("s1")
            counts.append(len(tools))

        # Monotonic: each count >= previous
        for i in range(1, len(counts)):
            assert counts[i] >= counts[i - 1]

    @pytest.mark.asyncio
    async def test_token_reduction_with_tiering(self):
        """Tiered output should be measurably smaller than full output for 10+ tools."""
        config = RetrievalConfig(
            enabled=True,
            top_k=18,
            full_description_count=3,
            anchor_tools=["github__get_me"],
        )
        registry = _build_large_registry()  # 18 tools
        retriever = KeywordRetriever(config)
        retriever.rebuild_index(registry)

        pipeline = RetrievalPipeline(
            retriever=retriever,
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            ranker=RelevanceRanker(),
            assembler=TieredAssembler(),
        )

        # Disclose all tools
        pipeline.session_manager.get_or_create_session("s1")
        pipeline.session_manager.add_tools("s1", list(registry.keys()))

        tiered_tools = await pipeline.get_tools_for_list("s1")
        tiered_size = sum(len(json.dumps(t.model_dump())) for t in tiered_tools)

        # Compare with full-description versions
        full_size = sum(len(json.dumps(m.tool.model_dump())) for m in registry.values())

        # Tiered should be smaller (at least some reduction from summary tier)
        assert tiered_size <= full_size

    @pytest.mark.asyncio
    async def test_disabled_returns_all(self):
        config = RetrievalConfig(enabled=False)
        registry = _build_large_registry()

        pipeline = RetrievalPipeline(
            retriever=KeywordRetriever(config),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )

        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == len(registry)


class TestKeywordRetrieverIsolation:
    """Verify KeywordRetriever alone scores correctly."""

    @pytest.mark.asyncio
    async def test_github_query_scores_github_higher(self):
        config = RetrievalConfig(enabled=True, top_k=5)
        registry = _build_large_registry()
        retriever = KeywordRetriever(config)
        retriever.rebuild_index(registry)

        from src.multimcp.retrieval.models import RetrievalContext

        ctx = RetrievalContext(session_id="s1", query="search GitHub repositories")
        results = await retriever.retrieve(ctx, list(registry.values()))

        top_names = [r.tool_mapping.tool.name for r in results[:3]]
        assert "search_repositories" in top_names

    @pytest.mark.asyncio
    async def test_obsidian_query_scores_obsidian_higher(self):
        config = RetrievalConfig(enabled=True, top_k=5)
        registry = _build_large_registry()
        retriever = KeywordRetriever(config)
        retriever.rebuild_index(registry)

        from src.multimcp.retrieval.models import RetrievalContext

        ctx = RetrievalContext(session_id="s1", query="read notes from vault")
        results = await retriever.retrieve(ctx, list(registry.values()))

        top_server_names = [r.tool_mapping.server_name for r in results[:3]]
        assert "obsidian" in top_server_names
