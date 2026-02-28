"""Edge-case and coverage-gap tests for the retrieval pipeline.

Covers code paths not exercised by the existing test suite:
- _tokenize with empty/stopword-only input
- rebuild_index with empty registry
- retrieve with candidates missing from index
- _score_tokens with empty inputs
- _get_specificity with non-dict schemas
- _truncate_description edge cases
- _strip_descriptions with nested 'items'
- assemble() when all tools fit in full tier
- compute_namespace_boosts with empty candidates
- Pipeline enabled path with ranker + assembler wired
"""

import pytest
from unittest.mock import MagicMock
from mcp import types

from src.multimcp.retrieval.keyword import KeywordRetriever, _tokenize
from src.multimcp.retrieval.ranker import RelevanceRanker, _get_specificity
from src.multimcp.retrieval.assembler import (
    TieredAssembler,
    _truncate_description,
    _strip_descriptions,
)
from src.multimcp.retrieval.namespace_filter import compute_namespace_boosts
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import RetrievalConfig, RetrievalContext, ScoredTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, desc: str = "A tool", props: dict = None) -> types.Tool:
    if props is None:
        props = {}
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": props},
    )


def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()
    return m


def _make_scored(
    server: str, name: str, score: float, desc: str = "A tool", props: dict = None
) -> ScoredTool:
    tool = _make_tool(name, desc, props)
    mapping = _make_mapping(server, tool)
    return ScoredTool(
        tool_key=f"{server}__{name}",
        tool_mapping=mapping,
        score=score,
    )


# ---------------------------------------------------------------------------
# _tokenize edge cases
# ---------------------------------------------------------------------------


class TestTokenizeEdgeCases:
    def test_empty_string(self):
        assert _tokenize("") == []

    def test_only_stopwords(self):
        assert _tokenize("the a an and or but in on at to for") == []

    def test_single_char_words_filtered(self):
        """Words of length 1 should be filtered out."""
        assert _tokenize("I a x") == []

    def test_underscore_splitting(self):
        tokens = _tokenize("get_file_contents")
        assert "get" in tokens
        assert "file" in tokens
        assert "contents" in tokens

    def test_mixed_case(self):
        tokens = _tokenize("GitHub_Search")
        assert "github" in tokens
        assert "search" in tokens


# ---------------------------------------------------------------------------
# KeywordRetriever edge cases
# ---------------------------------------------------------------------------


class TestKeywordRetrieverEdgeCases:
    def test_rebuild_index_empty_registry(self):
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        retriever.rebuild_index({})
        assert retriever._num_tools == 0
        assert retriever._tool_tokens == {}
        assert retriever._idf == {}

    @pytest.mark.asyncio
    async def test_retrieve_candidates_not_in_index(self):
        """Candidates whose key isn't in the index should be skipped."""
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        # Don't rebuild index — no tools indexed
        retriever.rebuild_index({})

        ctx = RetrievalContext(session_id="s1", query="search")
        mapping = _make_mapping("unknown", _make_tool("search"))
        results = await retriever.retrieve(ctx, [mapping])
        # Candidate not in index → skipped
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self):
        """Empty query should give all candidates score 0.5."""
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        tool = _make_tool("search", "Search the web")
        registry = {"exa__search": _make_mapping("exa", tool)}
        retriever.rebuild_index(registry)

        ctx = RetrievalContext(session_id="s1", query="")
        results = await retriever.retrieve(ctx, list(registry.values()))
        assert len(results) == 1
        assert results[0].score == 0.5

    @pytest.mark.asyncio
    async def test_retrieve_tool_with_none_description(self):
        """Tools with None description should still be indexed and scored."""
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        tool = _make_tool("search", None)
        # Override description to None (since _make_tool defaults to "A tool")
        tool = types.Tool(
            name="search",
            description=None,
            inputSchema={"type": "object", "properties": {}},
        )
        registry = {"exa__search": _make_mapping("exa", tool)}
        retriever.rebuild_index(registry)

        ctx = RetrievalContext(session_id="s1", query="search")
        results = await retriever.retrieve(ctx, list(registry.values()))
        assert len(results) == 1
        assert results[0].score > 0  # Name match should score > 0

    def test_score_tokens_empty_doc(self):
        """_score_tokens with empty doc_tokens returns 0.0."""
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        assert retriever._score_tokens(["search"], []) == 0.0

    def test_score_tokens_empty_query(self):
        """_score_tokens with empty query_tokens returns 0.0."""
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        assert retriever._score_tokens([], ["search"]) == 0.0

    def test_score_tokens_both_empty(self):
        config = RetrievalConfig(enabled=True, top_k=5)
        retriever = KeywordRetriever(config)
        assert retriever._score_tokens([], []) == 0.0


# ---------------------------------------------------------------------------
# _get_specificity edge cases
# ---------------------------------------------------------------------------


class TestGetSpecificityEdgeCases:
    def test_non_dict_schema(self):
        """inputSchema that isn't a dict should return 0."""
        scored = _make_scored("s", "t", 1.0)
        scored.tool_mapping.tool.inputSchema = "not-a-dict"
        assert _get_specificity(scored) == 0

    def test_none_schema(self):
        """inputSchema that is None should return 0."""
        scored = _make_scored("s", "t", 1.0)
        scored.tool_mapping.tool.inputSchema = None
        assert _get_specificity(scored) == 0

    def test_properties_not_dict(self):
        """properties field that isn't a dict should return 0."""
        scored = _make_scored("s", "t", 1.0)
        scored.tool_mapping.tool.inputSchema = {"properties": "not-a-dict"}
        assert _get_specificity(scored) == 0

    def test_missing_properties_key(self):
        """Schema without 'properties' key should return 0."""
        scored = _make_scored("s", "t", 1.0)
        scored.tool_mapping.tool.inputSchema = {"type": "object"}
        assert _get_specificity(scored) == 0

    def test_schema_with_properties(self):
        """Normal schema with properties should return count."""
        scored = _make_scored("s", "t", 1.0, props={"a": {}, "b": {}, "c": {}})
        assert _get_specificity(scored) == 3


# ---------------------------------------------------------------------------
# _truncate_description edge cases
# ---------------------------------------------------------------------------


class TestTruncateDescriptionEdgeCases:
    def test_empty_string(self):
        assert _truncate_description("") == ""

    def test_short_string(self):
        assert _truncate_description("Short desc.") == "Short desc."

    def test_exactly_at_max(self):
        """String at exactly _MAX_SUMMARY_CHARS should not be truncated."""
        desc = "x" * 80
        assert _truncate_description(desc) == desc

    def test_first_sentence_within_limit(self):
        desc = "First sentence. This is a much longer second sentence that pushes us well beyond the 80 char limit."
        result = _truncate_description(desc)
        assert result == "First sentence."

    def test_long_first_sentence(self):
        """If first sentence is longer than limit, fall back to char truncation."""
        desc = "x" * 100 + ". Short."
        result = _truncate_description(desc)
        assert len(result) <= 81  # 80 chars + ellipsis
        assert result.endswith("…")


# ---------------------------------------------------------------------------
# _strip_descriptions edge cases
# ---------------------------------------------------------------------------


class TestStripDescriptionsEdgeCases:
    def test_non_dict_passthrough(self):
        assert _strip_descriptions("string") == "string"
        assert _strip_descriptions(42) == 42
        assert _strip_descriptions(None) is None

    def test_strips_top_level_description(self):
        schema = {"type": "string", "description": "A string value"}
        result = _strip_descriptions(schema)
        assert "description" not in result
        assert result["type"] == "string"

    def test_strips_nested_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name"},
                "age": {"type": "integer", "description": "The age"},
            },
        }
        result = _strip_descriptions(schema)
        assert "description" not in result["properties"]["name"]
        assert "description" not in result["properties"]["age"]

    def test_strips_through_items(self):
        """Items key should be recursively processed."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "description": "An item",
                "properties": {
                    "id": {"type": "integer", "description": "Item ID"},
                },
            },
        }
        result = _strip_descriptions(schema)
        assert "description" not in result["items"]
        assert "description" not in result["items"]["properties"]["id"]

    def test_handles_empty_dict(self):
        assert _strip_descriptions({}) == {}


# ---------------------------------------------------------------------------
# TieredAssembler edge cases
# ---------------------------------------------------------------------------


class TestAssemblerEdgeCases:
    def test_all_tools_in_full_tier(self):
        """When full_description_count >= len(tools), all should be 'full' tier."""
        config = RetrievalConfig(enabled=True, full_description_count=10)
        assembler = TieredAssembler()
        tools = [
            _make_scored("s", "a", 1.0, desc="Tool A"),
            _make_scored("s", "b", 0.9, desc="Tool B"),
        ]
        result = assembler.assemble(tools, config)
        assert len(result) == 2
        assert all(t.tier == "full" for t in tools)  # All should be full tier

    def test_single_tool_full_tier(self):
        config = RetrievalConfig(enabled=True, full_description_count=1)
        assembler = TieredAssembler()
        tools = [_make_scored("s", "a", 1.0, desc="A detailed tool description")]
        result = assembler.assemble(tools, config)
        assert len(result) == 1
        assert result[0].description == "A detailed tool description"

    def test_summary_tier_truncates(self):
        config = RetrievalConfig(enabled=True, full_description_count=0)
        assembler = TieredAssembler()
        long_desc = "First sentence. " + "x" * 200
        tools = [_make_scored("s", "a", 1.0, desc=long_desc)]
        result = assembler.assemble(tools, config)
        assert len(result) == 1
        assert result[0].description == "First sentence."

    def test_never_mutates_originals(self):
        """Assembler must NOT mutate the original Tool objects in the registry."""
        config = RetrievalConfig(enabled=True, full_description_count=1)
        assembler = TieredAssembler()
        original_desc = "Original description that should not change"
        scored = _make_scored("s", "a", 1.0, desc=original_desc)
        original_tool = scored.tool_mapping.tool
        original_schema = original_tool.inputSchema

        assembler.assemble([scored], config)

        # Originals must be untouched
        assert original_tool.description == original_desc
        assert original_tool.inputSchema == original_schema


# ---------------------------------------------------------------------------
# compute_namespace_boosts edge cases
# ---------------------------------------------------------------------------


class TestNamespaceBoostsEdgeCases:
    def test_empty_candidates(self):
        result = compute_namespace_boosts({}, server_hint="github")
        assert result == {}

    def test_empty_candidates_no_hint(self):
        result = compute_namespace_boosts({}, server_hint=None)
        assert result == {}

    def test_no_matching_servers(self):
        """When hint doesn't match any server, all boosts are 1.0."""
        mapping = _make_mapping("exa", _make_tool("search"))
        result = compute_namespace_boosts(
            {"exa__search": mapping},
            server_hint="github",
        )
        assert result == {"exa__search": 1.0}

    def test_custom_boost_factor(self):
        mapping = _make_mapping("github", _make_tool("get_me"))
        result = compute_namespace_boosts(
            {"github__get_me": mapping},
            server_hint="github",
            boost_factor=2.0,
        )
        assert result == {"github__get_me": 2.0}


# ---------------------------------------------------------------------------
# Pipeline enabled path WITH ranker + assembler
# ---------------------------------------------------------------------------


class TestPipelineEnabledWithRankerAssembler:
    """Test the full enabled pipeline path with ranker and assembler wired."""

    @pytest.mark.asyncio
    async def test_enabled_with_ranker_assembler(self):
        """When ranker+assembler are provided, pipeline should rank and tier."""
        config = RetrievalConfig(
            enabled=True,
            top_k=5,
            full_description_count=1,
            anchor_tools=["github__get_me"],
        )
        registry = {
            "github__get_me": _make_mapping(
                "github",
                _make_tool("get_me", "Get GitHub user", {"user": {"type": "string"}}),
            ),
            "exa__search": _make_mapping(
                "exa",
                _make_tool("search", "Search the web", {"query": {"type": "string"}}),
            ),
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

        # Disclose second tool
        pipeline.session_manager.get_or_create_session("s1")
        pipeline.session_manager.add_tools("s1", ["exa__search"])

        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 2
        # First tool should be full tier (has complete description)
        assert tools[0].description is not None

    @pytest.mark.asyncio
    async def test_enabled_no_ranker_returns_raw_tools(self):
        """Without ranker+assembler, enabled path returns raw Tool objects."""
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
        )
        tool = _make_tool("get_me")
        registry = {"github__get_me": _make_mapping("github", tool)}
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            # No ranker/assembler
        )

        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 1
        assert tools[0] is tool  # Raw tool object, not tiered copy
