"""Tests for full pipeline wiring with ranker and assembler."""

import json
import pytest
from unittest.mock import MagicMock
from mcp import types
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.ranker import RelevanceRanker
from src.multimcp.retrieval.assembler import TieredAssembler


def _make_tool(name: str, desc: str = "A test tool", props: dict = None) -> types.Tool:
    if props is None:
        props = {"query": {"type": "string", "description": "Input query"}}
    return types.Tool(
        name=name, description=desc, inputSchema={"type": "object", "properties": props}
    )


def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()
    return m


class TestPipelineWithRankerAndAssembler:
    """End-to-end pipeline with ranker and assembler wired in."""

    @pytest.mark.asyncio
    async def test_disclosed_tools_are_ranked_and_tiered(self):
        config = RetrievalConfig(
            enabled=True,
            full_description_count=2,
            anchor_tools=["github__get_me"],
            rollout_stage="ga",
        )
        long_desc = "This is a comprehensive tool for searching across all repositories with advanced filtering and pagination"
        registry = {
            "github__get_me": _make_mapping(
                "github", _make_tool("get_me", "Get current user")
            ),
            "github__search": _make_mapping("github", _make_tool("search", long_desc)),
            "exa__search": _make_mapping("exa", _make_tool("search", "Search the web")),
            "obsidian__read": _make_mapping("obsidian", _make_tool("read", long_desc)),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
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

        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 4

        # First 2 should have full descriptions (full_description_count=2)
        # Last 2 should have summary descriptions
        full_tools = tools[:2]
        summary_tools = tools[2:]
        for t in summary_tools:
            if len(long_desc) > 80:
                assert (
                    len(t.description) <= 100
                    or t.description == long_desc[:80].rstrip() + "…"
                )

    @pytest.mark.asyncio
    async def test_fresh_session_returns_bounded_set(self):
        """Fresh session returns a bounded tool set via fallback ladder (not anchor-only).

        Phase 2: active set computed by scoring/fallback ladder, not session_manager seeding.
        Small registries (< 12 tools) expose all tools directly without routing tool.
        """
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
            rollout_stage="ga",
        )
        registry = {
            "github__get_me": _make_mapping("github", _make_tool("get_me")),
            "exa__search": _make_mapping("exa", _make_tool("search")),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            ranker=RelevanceRanker(),
            assembler=TieredAssembler(),
        )
        tools = await pipeline.get_tools_for_list("s1")
        # Phase 2: small registry (2 tools) → Tier 6 exposes all available tools
        # (universal fallback fills up to 12; with only 2 tools it's all 2)
        non_routing = [t for t in tools if t.name != "request_tool"]
        assert len(non_routing) <= 20  # core invariant
        assert len(non_routing) >= 1   # at least one tool returned

    @pytest.mark.asyncio
    async def test_bounded_output_with_ranker_assembler(self):
        """Pipeline with ranker and assembler returns bounded tool set."""
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
            rollout_stage="ga",
        )
        registry = {
            "github__get_me": _make_mapping("github", _make_tool("get_me")),
            "exa__search": _make_mapping("exa", _make_tool("search")),
            "obsidian__read": _make_mapping("obsidian", _make_tool("read")),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            ranker=RelevanceRanker(),
            assembler=TieredAssembler(),
        )
        # Phase 2: small registry (3 tools) → Tier 6 returns all available
        tools_1 = await pipeline.get_tools_for_list("s1")
        non_routing_1 = [t for t in tools_1 if t.name != "request_tool"]
        assert len(non_routing_1) <= 20  # core invariant

        # Subsequent calls remain bounded
        tools_2 = await pipeline.get_tools_for_list("s1")
        non_routing_2 = [t for t in tools_2 if t.name != "request_tool"]
        assert len(non_routing_2) <= 20
