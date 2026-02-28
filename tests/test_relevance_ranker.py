"""Tests for RelevanceRanker with specificity tiebreaking."""
import pytest
from unittest.mock import MagicMock
from mcp import types
from src.multimcp.retrieval.ranker import RelevanceRanker
from src.multimcp.retrieval.models import ScoredTool


def _make_scored(name: str, score: float, num_properties: int = 0) -> ScoredTool:
    tool = types.Tool(
        name=name,
        description="test",
        inputSchema={
            "type": "object",
            "properties": {f"prop{i}": {"type": "string"} for i in range(num_properties)},
        },
    )
    m = MagicMock()
    m.tool = tool
    return ScoredTool(tool_key=f"test__{name}", tool_mapping=m, score=score)


class TestRelevanceRanker:
    def setup_method(self):
        self.ranker = RelevanceRanker()

    def test_sorts_by_score_descending(self):
        tools = [
            _make_scored("low", 0.3),
            _make_scored("high", 0.9),
            _make_scored("mid", 0.6),
        ]
        ranked = self.ranker.rank(tools)
        scores = [t.score for t in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_tiebreak_by_specificity(self):
        """Equal scores: tool with more properties ranks first."""
        simple = _make_scored("simple", 0.8, num_properties=1)
        complex_ = _make_scored("complex", 0.8, num_properties=5)
        ranked = self.ranker.rank([simple, complex_])
        assert ranked[0].tool_key == "test__complex"

    def test_score_tolerance_for_tiebreak(self):
        """Scores within 0.05 are considered tied."""
        a = _make_scored("a", 0.81, num_properties=2)
        b = _make_scored("b", 0.79, num_properties=5)  # Lower score but more specific
        ranked = self.ranker.rank([a, b])
        # Within tolerance, so specificity tiebreak applies
        assert ranked[0].tool_key == "test__b"

    def test_score_beyond_tolerance_no_tiebreak(self):
        """Scores more than 0.05 apart: score wins, not specificity."""
        a = _make_scored("a", 0.9, num_properties=1)
        b = _make_scored("b", 0.7, num_properties=10)
        ranked = self.ranker.rank([a, b])
        assert ranked[0].tool_key == "test__a"

    def test_single_element(self):
        tools = [_make_scored("only", 0.5)]
        ranked = self.ranker.rank(tools)
        assert len(ranked) == 1
        assert ranked[0].tool_key == "test__only"

    def test_empty_list(self):
        assert self.ranker.rank([]) == []

    def test_deterministic(self):
        tools = [
            _make_scored("a", 0.5, 2),
            _make_scored("b", 0.5, 2),
            _make_scored("c", 0.5, 2),
        ]
        r1 = [t.tool_key for t in self.ranker.rank(tools)]
        r2 = [t.tool_key for t in self.ranker.rank(tools)]
        assert r1 == r2
