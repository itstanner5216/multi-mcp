"""Tests for NAMESPACE_ALIASES exact key lookup — 07-01-PLAN.md mandatory tests.

Covers:
- Exact server name key lookup (github, context7)
- No substring matching (gh does not match github)
"""
from __future__ import annotations

from src.multimcp.retrieval.bmx_retriever import BMXFRetriever, NAMESPACE_ALIASES


def _make_retriever() -> BMXFRetriever:
    from src.multimcp.retrieval.models import RetrievalConfig
    return BMXFRetriever(config=RetrievalConfig())


class TestExactKeyLookup:
    def test_exact_key_lookup(self):
        """'github' key must return aliases including 'repository'."""
        assert "github" in NAMESPACE_ALIASES
        assert "repository" in NAMESPACE_ALIASES["github"]

    def test_context7_exact_key_lookup(self):
        """'context7' key must return aliases including 'documentation'."""
        assert "context7" in NAMESPACE_ALIASES
        assert "documentation" in NAMESPACE_ALIASES["context7"]

    def test_github_aliases_populated_on_generate(self):
        """_generate_aliases with namespace='github' must include 'repository'."""
        retriever = _make_retriever()
        aliases = retriever._generate_aliases("search_repositories", "github")
        assert "repository" in aliases, f"Expected 'repository' in aliases: {aliases!r}"

    def test_context7_aliases_populated_on_generate(self):
        """_generate_aliases with namespace='context7' must include 'documentation'."""
        retriever = _make_retriever()
        aliases = retriever._generate_aliases("get_library_docs", "context7")
        assert "documentation" in aliases, f"Expected 'documentation' in aliases: {aliases!r}"


class TestNoSubstringMatching:
    def test_no_substring_matching(self):
        """'gh' must NOT match 'github' key — only exact server names match."""
        retriever = _make_retriever()
        aliases = retriever._generate_aliases("some_tool", "gh")
        # 'gh' is not a key in NAMESPACE_ALIASES, so aliases must not include github terms
        # (they may include ACTION_ALIASES from tool name words, but not namespace aliases)
        assert "repository" not in aliases, (
            "'gh' should not match 'github' key — exact lookup required"
        )

    def test_fs_does_not_match_filesystem(self):
        """'fs' must NOT match 'filesystem' key."""
        retriever = _make_retriever()
        aliases = retriever._generate_aliases("read_file", "fs")
        assert "folder" not in aliases, (
            "'fs' should not match 'filesystem' key — exact lookup required"
        )

    def test_brave_search_exact_match(self):
        """'brave-search' key matches exactly (hyphenated name)."""
        assert "brave-search" in NAMESPACE_ALIASES
        retriever = _make_retriever()
        aliases = retriever._generate_aliases("web_search", "brave-search")
        assert "web_search" in aliases or "find" in aliases, (
            f"Expected brave-search aliases in: {aliases!r}"
        )
