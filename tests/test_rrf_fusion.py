"""Tests for weighted RRF fusion and alpha-decay (TEST-06).

Requirements: FUSION-01, FUSION-02
"""

from __future__ import annotations

import math

import pytest

from src.multimcp.retrieval.fusion import RRF_K, compute_alpha, weighted_rrf
from src.multimcp.retrieval.models import ScoredTool


def _make_tool(key: str, score: float = 1.0) -> ScoredTool:
    """Build a minimal ScoredTool for testing (no real ToolMapping needed)."""
    return ScoredTool(tool_key=key, tool_mapping=None, score=score, tier="full")  # type: ignore[arg-type]


class TestWeightedRRF:
    def test_empty_lists_return_empty(self) -> None:
        assert weighted_rrf([], [], 0.85) == []

    def test_single_list_env_only(self) -> None:
        env = [_make_tool("a"), _make_tool("b"), _make_tool("c")]
        result = weighted_rrf(env, [], 0.85)
        assert len(result) == 3
        keys = [t.tool_key for t in result]
        assert keys == ["a", "b", "c"], "env order preserved when conv is empty"

    def test_single_list_conv_only(self) -> None:
        conv = [_make_tool("x"), _make_tool("y")]
        result = weighted_rrf([], conv, 0.0)
        keys = [t.tool_key for t in result]
        assert keys == ["x", "y"]

    def test_alpha_1_favors_env_order(self) -> None:
        env = [_make_tool("first"), _make_tool("second"), _make_tool("third")]
        conv = [_make_tool("third"), _make_tool("second"), _make_tool("first")]
        result = weighted_rrf(env, conv, alpha=1.0)
        assert result[0].tool_key == "first"
        assert result[-1].tool_key == "third"

    def test_alpha_0_favors_conv_order(self) -> None:
        env = [_make_tool("third"), _make_tool("second"), _make_tool("first")]
        conv = [_make_tool("first"), _make_tool("second"), _make_tool("third")]
        result = weighted_rrf(env, conv, alpha=0.0)
        assert result[0].tool_key == "first"

    def test_tool_in_both_lists_gets_combined_score(self) -> None:
        shared = "shared_tool"
        env = [_make_tool(shared), _make_tool("env_only")]
        conv = [_make_tool(shared), _make_tool("conv_only")]
        result = weighted_rrf(env, conv, alpha=0.5)
        # shared_tool ranks 0 in both -> highest combined score
        assert result[0].tool_key == shared

    def test_tool_in_one_list_still_appears(self) -> None:
        env = [_make_tool("a"), _make_tool("b")]
        conv = [_make_tool("c")]
        result = weighted_rrf(env, conv, alpha=0.5)
        keys = {t.tool_key for t in result}
        assert keys == {"a", "b", "c"}

    def test_rrf_formula_correctness(self) -> None:
        env = [_make_tool("t1"), _make_tool("t2")]
        conv = [_make_tool("t1"), _make_tool("t2")]
        alpha = 0.5
        result = weighted_rrf(env, conv, alpha)
        # t1: rank 1 in both -> score = 0.5/(10+1) + 0.5/(10+1) = 1/11
        assert result[0].score == pytest.approx(1.0 / 11, abs=1e-6)
        # t2: rank 2 in both -> score = 0.5/12 + 0.5/12 = 1/12
        assert result[1].score == pytest.approx(1.0 / 12, abs=1e-6)

    def test_output_sorted_descending(self) -> None:
        env = [_make_tool(f"t{i}") for i in range(5)]
        conv = list(reversed(env))
        result = weighted_rrf(env, conv, alpha=0.5)
        scores = [t.score for t in result]
        assert scores == sorted(scores, reverse=True)


class TestComputeAlpha:
    def test_turn_0_returns_085(self) -> None:
        alpha = compute_alpha(0, workspace_confidence=0.8, conv_confidence=0.5)
        assert alpha == pytest.approx(0.85, abs=0.001)

    def test_turn_1_decays(self) -> None:
        alpha = compute_alpha(1, workspace_confidence=0.8, conv_confidence=0.5)
        assert 0.15 < alpha < 0.85

    def test_turn_5_midpoint(self) -> None:
        alpha = compute_alpha(5, workspace_confidence=0.8, conv_confidence=0.5)
        expected = max(0.15, 0.85 * math.exp(-0.25 * 5))
        assert alpha == pytest.approx(expected, abs=0.001)

    def test_turn_10_at_floor(self) -> None:
        alpha = compute_alpha(10, workspace_confidence=0.8, conv_confidence=0.5)
        assert alpha == pytest.approx(0.15, abs=0.05)

    def test_turn_100_still_at_floor(self) -> None:
        alpha = compute_alpha(100, workspace_confidence=0.8, conv_confidence=0.5)
        assert alpha == pytest.approx(0.15, abs=0.001)

    def test_low_workspace_confidence_reduces_alpha(self) -> None:
        high = compute_alpha(2, workspace_confidence=0.8, conv_confidence=0.5)
        low = compute_alpha(2, workspace_confidence=0.3, conv_confidence=0.5)
        assert low < high

    def test_explicit_tool_mention_snaps_to_015(self) -> None:
        alpha = compute_alpha(
            3, workspace_confidence=0.8, conv_confidence=0.9,
            explicit_tool_mention=True,
        )
        assert alpha == pytest.approx(0.15, abs=0.001)

    def test_explicit_mention_ignored_below_conv_threshold(self) -> None:
        alpha = compute_alpha(
            3, workspace_confidence=0.8, conv_confidence=0.5,
            explicit_tool_mention=True,
        )
        # conv_confidence < 0.70, so override should NOT snap to 0.15
        assert alpha > 0.15

    def test_roots_changed_resets_to_080(self) -> None:
        alpha = compute_alpha(
            8, workspace_confidence=0.8, conv_confidence=0.5, roots_changed=True
        )
        assert alpha >= 0.80

    def test_roots_changed_overrides_decay(self) -> None:
        # At turn 10 without roots change, alpha ~= 0.15
        # With roots change, must be >= 0.80
        alpha = compute_alpha(10, 0.8, 0.5, roots_changed=True)
        assert alpha >= 0.80

    def test_never_below_015(self) -> None:
        for turn in [0, 1, 5, 10, 50]:
            alpha = compute_alpha(turn, workspace_confidence=0.1, conv_confidence=0.1)
            assert alpha >= 0.15
