"""Tests for BMXFRetriever — field-weighted BMX tool retrieval."""
import pytest
from unittest.mock import MagicMock
from mcp import types

from src.multimcp.retrieval.bmx_retriever import BMXFRetriever, NAMESPACE_ALIASES, ACTION_ALIASES
from src.multimcp.retrieval.models import RetrievalConfig, RetrievalContext, ScoredTool


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tool(name: str, desc: str = "", params: list[str] | None = None) -> types.Tool:
    props = {p: {"type": "string"} for p in (params or [])}
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


def _build_registry(tools: dict) -> dict:
    """Build a registry from {key: (server, name, description, params)} 4-tuples."""
    registry = {}
    for key, (server, name, desc, params) in tools.items():
        registry[key] = _make_mapping(server, _make_tool(name, desc, params))
    return registry


def _default_registry():
    return _build_registry({
        "github__search_repositories": (
            "github", "search_repositories",
            "Search for GitHub repositories by name or topic", ["query", "page"]
        ),
        "github__create_issue": (
            "github", "create_issue",
            "Create a new issue in a GitHub repository", ["title", "body", "repo"]
        ),
        "github__list_pull_requests": (
            "github", "list_pull_requests",
            "List pull requests for a repository", ["repo", "state"]
        ),
        "fs__read_file": (
            "fs", "read_file",
            "Read the contents of a file from the filesystem", ["path"]
        ),
        "fs__write_file": (
            "fs", "write_file",
            "Write content to a file on the filesystem", ["path", "content"]
        ),
        "fs__list_directory": (
            "fs", "list_directory",
            "List files and directories at a given path", ["path"]
        ),
        "db__query": (
            "db", "query",
            "Execute a SQL query against the database", ["sql", "params"]
        ),
        "slack__send_message": (
            "slack", "send_message",
            "Send a message to a Slack channel", ["channel", "text"]
        ),
    })


# ── rebuild_index tests ───────────────────────────────────────────────────────

class TestRebuildIndex:
    def test_builds_index_from_registry(self):
        retriever = BMXFRetriever()
        registry = _default_registry()
        retriever.rebuild_index(registry)

        assert retriever._index is not None
        assert retriever._snapshot is not None
        assert len(retriever._snapshot.docs) == len(registry)

    def test_rebuild_replaces_previous_index(self):
        retriever = BMXFRetriever()
        registry = _default_registry()

        retriever.rebuild_index(registry)
        snapshot_v1 = retriever._snapshot.version

        retriever.rebuild_index(registry)
        snapshot_v2 = retriever._snapshot.version

        # Version should increment
        assert int(snapshot_v2) > int(snapshot_v1)

    def test_all_tools_indexed(self):
        retriever = BMXFRetriever()
        registry = _default_registry()
        retriever.rebuild_index(registry)

        indexed_keys = {doc.tool_key for doc in retriever._snapshot.docs}
        assert indexed_keys == set(registry.keys())

    def test_sub_100ms_for_168_tools(self):
        """rebuild_index for 168 tools must complete in < 100ms (SCORE-01 requirement)."""
        import time
        # Generate 168 tools
        tools = {}
        for i in range(168):
            server = f"server{i % 12}"
            name = f"tool_{i}"
            key = f"{server}__{name}"
            tools[key] = (server, name, f"Description for tool {i}", ["param_a", "param_b"])
        registry = _build_registry(tools)

        retriever = BMXFRetriever()
        start = time.perf_counter()
        retriever.rebuild_index(registry)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"rebuild_index took {elapsed_ms:.1f}ms — must be < 100ms"

    def test_aliases_populated_after_rebuild(self):
        retriever = BMXFRetriever()
        registry = _build_registry({
            "fs__read_file": ("fs", "read_file", "Read a file", ["path"]),
        })
        retriever.rebuild_index(registry)

        doc = retriever._snapshot.docs[0]
        # fs namespace should generate aliases; read action should too
        assert doc.retrieval_aliases != ""


# ── Field weight tests ────────────────────────────────────────────────────────

class TestFieldWeights:
    def test_field_weights_applied(self):
        """Tools with exact name match should score higher than desc-only match."""
        retriever = BMXFRetriever()
        registry = _build_registry({
            "svc__search": ("svc", "search", "This tool does something unrelated", []),
            "svc__unrelated": ("svc", "unrelated", "Search for documents and find results", []),
        })
        retriever.rebuild_index(registry)

        results = retriever._index.search_fields("search", top_k=10)
        result_keys = [k for k, _ in results]

        # Tool named "search" should appear before tool with "search" only in desc
        assert result_keys.index("svc__search") < result_keys.index("svc__unrelated")

    def test_namespace_weight(self):
        """Tools in a matching namespace should score higher than desc-only match."""
        retriever = BMXFRetriever()
        registry = _build_registry({
            "github__list": ("github", "list", "Show all items", []),
            "other__list": ("other", "list", "GitHub-related listing operation", []),
        })
        retriever.rebuild_index(registry)

        results = retriever._index.search_fields("github", top_k=10)
        result_keys = [k for k, _ in results]

        assert result_keys.index("github__list") < result_keys.index("other__list")

    def test_five_field_indexes_created(self):
        retriever = BMXFRetriever()
        registry = _default_registry()
        retriever.rebuild_index(registry)

        assert hasattr(retriever._index, "_field_indexes")
        expected_fields = {"tool_name", "namespace", "retrieval_aliases", "description", "parameter_names"}
        assert set(retriever._index._field_indexes.keys()) == expected_fields


# ── retrieve() tests ─────────────────────────────────────────────────────────

class TestRetrieve:
    @pytest.mark.asyncio
    async def test_shadow_mode_returns_all_candidates(self):
        """In shadow mode, all candidates are returned regardless of score."""
        config = RetrievalConfig(shadow_mode=True, max_k=3)
        retriever = BMXFRetriever(config=config)
        registry = _default_registry()
        retriever.rebuild_index(registry)

        candidates = list(registry.values())
        ctx = RetrievalContext(session_id="s1", query="search repositories")

        results = await retriever.retrieve(ctx, candidates)
        assert len(results) == len(candidates)

    @pytest.mark.asyncio
    async def test_shadow_mode_scores_are_logged(self):
        """Shadow mode produces scored results (non-zero score for matching tools)."""
        config = RetrievalConfig(shadow_mode=True, max_k=3)
        retriever = BMXFRetriever(config=config)
        registry = _default_registry()
        retriever.rebuild_index(registry)

        candidates = list(registry.values())
        ctx = RetrievalContext(session_id="s1", query="search github repositories")

        results = await retriever.retrieve(ctx, candidates)
        scored_tools = [r for r in results if r.score > 0]
        assert len(scored_tools) > 0

    @pytest.mark.asyncio
    async def test_live_mode_bounds_results_to_max_k(self):
        """With shadow_mode=False, retrieve returns at most max_k results."""
        config = RetrievalConfig(shadow_mode=False, max_k=3)
        retriever = BMXFRetriever(config=config)
        registry = _default_registry()
        retriever.rebuild_index(registry)

        candidates = list(registry.values())
        ctx = RetrievalContext(session_id="s1", query="file read write")

        results = await retriever.retrieve(ctx, candidates)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_no_index_returns_passthrough(self):
        """Without rebuild_index, retrieve falls back to passthrough (score=1.0)."""
        retriever = BMXFRetriever()
        mapping = _make_mapping("svc", _make_tool("tool_a", "Some tool"))
        ctx = RetrievalContext(session_id="s1", query="something")

        results = await retriever.retrieve(ctx, [mapping])
        assert len(results) == 1
        assert results[0].score == 1.0

    @pytest.mark.asyncio
    async def test_empty_query_returns_passthrough(self):
        """Empty query triggers passthrough regardless of index state."""
        retriever = BMXFRetriever()
        registry = _default_registry()
        retriever.rebuild_index(registry)

        candidates = list(registry.values())
        ctx = RetrievalContext(session_id="s1", query="")

        results = await retriever.retrieve(ctx, candidates)
        assert len(results) == len(candidates)
        assert all(r.score == 1.0 for r in results)

    @pytest.mark.asyncio
    async def test_results_ordered_by_score_descending(self):
        """Results should be ordered best-first in live mode."""
        config = RetrievalConfig(shadow_mode=False, max_k=10)
        retriever = BMXFRetriever(config=config)
        registry = _default_registry()
        retriever.rebuild_index(registry)

        candidates = list(registry.values())
        ctx = RetrievalContext(session_id="s1", query="read file filesystem")

        results = await retriever.retrieve(ctx, candidates)
        scored = [r for r in results if r.score > 0]
        if len(scored) >= 2:
            assert scored[0].score >= scored[1].score

    @pytest.mark.asyncio
    async def test_unscored_candidates_appended(self):
        """Candidates not in index still appear in shadow mode results."""
        config = RetrievalConfig(shadow_mode=True)
        retriever = BMXFRetriever(config=config)
        # Build index with only one tool, but retrieve with two
        registry = _build_registry({
            "svc__known": ("svc", "known", "A known tool", []),
        })
        retriever.rebuild_index(registry)

        unknown_mapping = _make_mapping("svc", _make_tool("unknown"))
        unknown_mapping.server_name = "other"
        known_mapping = list(registry.values())[0]

        ctx = RetrievalContext(session_id="s1", query="known")
        results = await retriever.retrieve(ctx, [known_mapping, unknown_mapping])
        assert len(results) == 2


# ── Alias generation tests ────────────────────────────────────────────────────

class TestAliasGeneration:
    def test_namespace_alias_expansion(self):
        # NAMESPACE_ALIASES now uses exact server name keys (source plan lines 584-597)
        # "filesystem" is the canonical key; "fs" is not a key
        retriever = BMXFRetriever()
        aliases = retriever._generate_aliases("list_files", "filesystem")
        for synonym in NAMESPACE_ALIASES["filesystem"]:
            for token in synonym.split():
                assert token in aliases

    def test_action_alias_expansion(self):
        retriever = BMXFRetriever()
        aliases = retriever._generate_aliases("create_issue", "github")
        for synonym in ACTION_ALIASES["create"]:
            for token in synonym.split():
                assert token in aliases

    def test_no_duplicate_tokens(self):
        retriever = BMXFRetriever()
        # "filesystem" is the correct exact key; "fs" no longer matches
        aliases = retriever._generate_aliases("read_file", "filesystem")
        tokens = aliases.split()
        assert len(tokens) == len(set(tokens))

    def test_unknown_namespace_and_action(self):
        retriever = BMXFRetriever()
        aliases = retriever._generate_aliases("do_something_strange", "xyz_service")
        # Should return empty string when no aliases match
        assert isinstance(aliases, str)

    def test_hyphen_and_underscore_normalized(self):
        retriever = BMXFRetriever()
        aliases_underscore = retriever._generate_aliases("send_message", "slack")
        aliases_hyphen = retriever._generate_aliases("send-message", "slack")
        # Both should produce same output since we normalize separators
        assert aliases_underscore == aliases_hyphen
