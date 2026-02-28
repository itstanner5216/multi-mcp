"""Tests for namespace pre-filter boost utility."""
import pytest
from unittest.mock import MagicMock
from src.multimcp.retrieval.namespace_filter import compute_namespace_boosts


def _make_mapping(server_name: str):
    m = MagicMock()
    m.server_name = server_name
    return m


class TestNamespaceBoosts:
    def test_no_hint_all_boost_1(self):
        candidates = {
            "github__get_me": _make_mapping("github"),
            "exa__search": _make_mapping("exa"),
        }
        boosts = compute_namespace_boosts(candidates, server_hint=None)
        assert all(v == 1.0 for v in boosts.values())

    def test_hint_boosts_matching_server(self):
        candidates = {
            "github__get_me": _make_mapping("github"),
            "github__search": _make_mapping("github"),
            "exa__search": _make_mapping("exa"),
        }
        boosts = compute_namespace_boosts(candidates, server_hint="github")
        assert boosts["github__get_me"] == 1.5
        assert boosts["github__search"] == 1.5
        assert boosts["exa__search"] == 1.0

    def test_hint_no_match_all_1(self):
        candidates = {
            "github__get_me": _make_mapping("github"),
        }
        boosts = compute_namespace_boosts(candidates, server_hint="obsidian")
        assert boosts["github__get_me"] == 1.0

    def test_empty_candidates(self):
        boosts = compute_namespace_boosts({}, server_hint="github")
        assert boosts == {}

    def test_boost_factor_configurable(self):
        candidates = {"github__get_me": _make_mapping("github")}
        boosts = compute_namespace_boosts(candidates, server_hint="github", boost_factor=2.0)
        assert boosts["github__get_me"] == 2.0
