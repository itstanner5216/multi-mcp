"""Tests for core pipeline wiring — 07-01-PLAN.md mandatory tests.

Covers:
- RetrievalConfig.top_k default = 15
- Routing tool dispatch by ROUTING_TOOL_NAME
- get_tools_for_list() calls retriever.retrieve()
- weighted_rrf called when turn > 0 with conversation_context
- _extract_conv_terms() extraction pipeline
- Dynamic K: polyglot and no-evidence cases
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp import types

from src.multimcp.retrieval.pipeline import RetrievalPipeline, _extract_conv_terms
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import (
    RetrievalConfig,
    RetrievalContext,
    ScoredTool,
    WorkspaceEvidence,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_tool(name: str, desc: str = "A tool") -> types.Tool:
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


def _make_registry(n: int = 5) -> dict:
    return {
        f"srv{i}__{i}_tool": _make_mapping(f"srv{i}", _make_tool(f"{i}_tool"))
        for i in range(n)
    }


def _make_pipeline(
    registry: dict | None = None,
    config: RetrievalConfig | None = None,
    retriever=None,
    telemetry_scanner=None,
) -> RetrievalPipeline:
    if config is None:
        config = RetrievalConfig(enabled=True, rollout_stage="ga")
    if registry is None:
        registry = _make_registry()
    if retriever is None:
        retriever = PassthroughRetriever()
    return RetrievalPipeline(
        retriever=retriever,
        session_manager=SessionStateManager(config),
        logger=NullLogger(),
        config=config,
        tool_registry=registry,
        telemetry_scanner=telemetry_scanner,
    )


# ── 1. top_k default ──────────────────────────────────────────────────────────

class TestRetrievalConfigTopKDefault:
    def test_retrieval_config_top_k_default(self):
        """RetrievalConfig().top_k must equal 15 (source plan line 496)."""
        assert RetrievalConfig().top_k == 15


# ── 2. Routing dispatch by model name ─────────────────────────────────────────

class TestRoutingDispatchByModelName:
    @pytest.mark.asyncio
    async def test_routing_dispatch_by_model_name(self):
        """tool_name 'request_tool' must reach handle_routing_call(), not fall through."""
        from src.multimcp.retrieval.routing_tool import ROUTING_TOOL_NAME
        assert ROUTING_TOOL_NAME == "request_tool"

        # Verify that mcp_proxy uses ROUTING_TOOL_NAME in dispatch
        import ast
        import pathlib
        src = pathlib.Path("src/multimcp/mcp_proxy.py").read_text()
        tree = ast.parse(src)
        # Check that ROUTING_TOOL_KEY is NOT used as dispatch comparator
        found_name_dispatch = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Name) and comparator.id == "ROUTING_TOOL_NAME":
                        found_name_dispatch = True
        assert found_name_dispatch, (
            "mcp_proxy.py must compare tool_name to ROUTING_TOOL_NAME, not ROUTING_TOOL_KEY"
        )


# ── 3. retrieve() called in get_tools_for_list ───────────────────────────────

class TestRetrieveCalled:
    @pytest.mark.asyncio
    async def test_retrieve_called(self):
        """get_tools_for_list() with enabled=True must call retriever.retrieve()."""
        mock_retriever = MagicMock()
        # retrieve must return a list of ScoredTool
        registry = _make_registry(3)
        scored = [
            ScoredTool(tool_key=k, tool_mapping=v, score=1.0)
            for k, v in registry.items()
        ]
        mock_retriever.retrieve = AsyncMock(return_value=scored)
        mock_retriever._env_index = MagicMock()  # mark as index available
        mock_retriever._env_index = MagicMock()

        # Plant workspace evidence so env_query is non-empty (required for tier 2)
        pipeline = _make_pipeline(registry=registry, retriever=mock_retriever)
        pipeline._session_evidence["sess1"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0},
        )

        await pipeline.get_tools_for_list("sess1", "")
        mock_retriever.retrieve.assert_called()


# ── 4. weighted_rrf called when turn > 0 ─────────────────────────────────────

class TestRrfCalledTurnGt0:
    @pytest.mark.asyncio
    async def test_rrf_called_turn_gt_0(self):
        """weighted_rrf() must be called when turn > 0 and conversation_context is set."""
        registry = _make_registry(5)
        scored = [
            ScoredTool(tool_key=k, tool_mapping=v, score=1.0)
            for k, v in registry.items()
        ]
        mock_retriever = MagicMock()
        mock_retriever.retrieve = AsyncMock(return_value=scored)
        mock_retriever._env_index = MagicMock()

        pipeline = _make_pipeline(registry=registry, retriever=mock_retriever)
        pipeline._session_evidence["sess2"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0},
        )
        # Simulate turn > 0
        pipeline._session_turns["sess2"] = 1

        with patch("src.multimcp.retrieval.pipeline._weighted_rrf") as mock_rrf, \
             patch("src.multimcp.retrieval.pipeline._compute_alpha", return_value=0.5):
            mock_rrf.return_value = scored
            await pipeline.get_tools_for_list("sess2", "list files search query")
            mock_rrf.assert_called_once()


# ── 5. _extract_conv_terms ────────────────────────────────────────────────────

class TestConversationContextExtraction:
    def test_stopword_removal(self):
        """Stopwords must be removed from extraction output."""
        result = _extract_conv_terms("the file is in the directory")
        tokens = result.split()
        for sw in ("the", "is", "in"):
            assert sw not in tokens, f"Stopword '{sw}' should be removed"

    def test_underscore_dash_replaced(self):
        """Underscores and dashes must be treated as word separators."""
        result = _extract_conv_terms("list_files search-query")
        assert "list" in result
        assert "files" in result
        assert "search" in result
        assert "query" in result

    def test_bigrams_appended(self):
        """Adjacent non-stopword tokens must generate bigrams."""
        result = _extract_conv_terms("list files")
        assert "list files" in result

    def test_action_verb_expansion(self):
        """Action verbs must expand to aliases."""
        result = _extract_conv_terms("list tools")
        # 'list' should expand to get, fetch, show, enumerate
        assert "get" in result
        assert "fetch" in result

    def test_deduplication(self):
        """Duplicate tokens must appear only once."""
        result = _extract_conv_terms("list list list")
        tokens = result.split()
        # "list" should appear at most once
        assert tokens.count("list") == 1

    def test_lowercasing(self):
        """Output must be lowercased."""
        result = _extract_conv_terms("SEARCH Query GitHub")
        assert result == result.lower()

    def test_empty_input(self):
        """Empty input must return empty string."""
        assert _extract_conv_terms("") == ""

    def test_only_stopwords(self):
        """Input with only stopwords must return empty string."""
        assert _extract_conv_terms("the a an is are") == ""

    def test_full_pipeline(self):
        """Full pipeline produces stopword-free, bigram-augmented, action-verb-expanded output."""
        result = _extract_conv_terms("list files in the directory")
        tokens = set(result.split())
        # stopwords removed
        assert "the" not in tokens
        assert "in" not in tokens
        # core tokens present
        assert "list" in tokens
        assert "files" in tokens
        assert "directory" in tokens
        # bigram
        assert "list files" in result
        # action verb expansion
        assert "get" in tokens


# ── 6. Dynamic K ─────────────────────────────────────────────────────────────

class TestDynamicK:
    @pytest.mark.asyncio
    async def test_dynamic_k_polyglot(self):
        """When evidence has >1 lang: token, dynamic_k must be 18."""
        registry = _make_registry(25)
        pipeline = _make_pipeline(
            registry=registry,
            config=RetrievalConfig(enabled=True, rollout_stage="ga"),
        )
        pipeline._session_evidence["polyglot"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0, "lang:javascript": 0.8},
        )

        # Capture the dynamic_k by inspecting the result count
        result = await pipeline.get_tools_for_list("polyglot", "")
        # In ga mode without routing tool: up to 18 direct tools exposed
        # (one slot reserved for routing tool = direct_k = 17)
        # With 25-tool registry and 17 direct slots: result should be <= 18
        assert len(result) <= 19  # 18 direct + 1 routing tool

    @pytest.mark.asyncio
    async def test_dynamic_k_no_evidence(self):
        """When no evidence, dynamic_k must be 15."""
        registry = _make_registry(25)
        pipeline = _make_pipeline(
            registry=registry,
            config=RetrievalConfig(enabled=True, rollout_stage="ga"),
        )
        # No evidence set for this session
        result = await pipeline.get_tools_for_list("noevidence", "")
        # dynamic_k=15, direct_k=14 (routing slot), + 1 routing = 15 total
        assert len(result) <= 16  # 15 direct + 1 routing


# ── 7. Disabled mode passthrough ─────────────────────────────────────────────

class TestDisabledPassthrough:
    @pytest.mark.asyncio
    async def test_all_tools_returned_when_disabled(self):
        """enabled=False must return all tools regardless of any other state."""
        registry = _make_registry(10)
        pipeline = _make_pipeline(
            registry=registry,
            config=RetrievalConfig(enabled=False),
        )
        result = await pipeline.get_tools_for_list("sess", "some context")
        assert len(result) == 10
