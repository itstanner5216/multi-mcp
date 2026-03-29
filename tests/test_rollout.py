"""Tests for canary rollout session assignment."""

from __future__ import annotations

import uuid

import pytest

from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.rollout import get_session_group, is_canary_session


class TestIsCanarySession:
    def test_zero_percent_always_control(self) -> None:
        for i in range(100):
            assert is_canary_session(f"session-{i}", 0.0) is False

    def test_hundred_percent_always_canary(self) -> None:
        for i in range(100):
            assert is_canary_session(f"session-{i}", 100.0) is True

    def test_deterministic(self) -> None:
        sid = "determinism-check-session"
        result1 = is_canary_session(sid, 50.0)
        result2 = is_canary_session(sid, 50.0)
        assert result1 == result2

    def test_different_sessions_get_different_assignments(self) -> None:
        results = {is_canary_session(f"s-{i}", 50.0) for i in range(100)}
        assert len(results) == 2, "At 50%, should see both True and False"

    def test_distribution_at_50_percent(self) -> None:
        n = 1000
        canary_count = sum(
            is_canary_session(str(uuid.uuid4()), 50.0) for _ in range(n)
        )
        assert 350 < canary_count < 650, f"Expected ~500, got {canary_count}"

    def test_distribution_at_10_percent(self) -> None:
        n = 1000
        canary_count = sum(
            is_canary_session(str(uuid.uuid4()), 10.0) for _ in range(n)
        )
        assert 50 < canary_count < 200, f"Expected ~100, got {canary_count}"

    def test_boundary_tiny_percentage(self) -> None:
        # Should not raise; most sessions should be control
        results = [is_canary_session(f"s-{i}", 0.01) for i in range(100)]
        assert sum(results) < 10

    def test_boundary_near_full(self) -> None:
        results = [is_canary_session(f"s-{i}", 99.99) for i in range(100)]
        assert sum(results) > 90

    def test_negative_percentage_treated_as_zero(self) -> None:
        assert is_canary_session("any", -5.0) is False

    def test_over_100_treated_as_full(self) -> None:
        assert is_canary_session("any", 150.0) is True


class TestGetSessionGroup:
    def test_shadow_always_control(self) -> None:
        config = RetrievalConfig(rollout_stage="shadow", canary_percentage=50.0)
        for i in range(20):
            assert get_session_group(f"s-{i}", config) == "control"

    def test_ga_always_canary(self) -> None:
        config = RetrievalConfig(rollout_stage="ga", canary_percentage=0.0)
        for i in range(20):
            assert get_session_group(f"s-{i}", config) == "canary"

    def test_canary_stage_uses_hash(self) -> None:
        config = RetrievalConfig(rollout_stage="canary", canary_percentage=50.0)
        groups = {get_session_group(f"s-{i}", config) for i in range(100)}
        assert groups == {"canary", "control"}

    def test_canary_stage_zero_percent(self) -> None:
        config = RetrievalConfig(rollout_stage="canary", canary_percentage=0.0)
        for i in range(20):
            assert get_session_group(f"s-{i}", config) == "control"

    def test_canary_stage_hundred_percent(self) -> None:
        config = RetrievalConfig(rollout_stage="canary", canary_percentage=100.0)
        for i in range(20):
            assert get_session_group(f"s-{i}", config) == "canary"

    def test_deterministic_with_config(self) -> None:
        config = RetrievalConfig(rollout_stage="canary", canary_percentage=30.0)
        sid = "stable-id"
        r1 = get_session_group(sid, config)
        r2 = get_session_group(sid, config)
        assert r1 == r2
