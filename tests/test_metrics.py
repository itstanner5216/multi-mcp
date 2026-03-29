"""Tests for rolling metric aggregation and alert checking (Phase 4)."""

from __future__ import annotations

import pytest

from src.multimcp.retrieval.metrics import (
    AlertChecker,
    MetricSnapshot,
    RollingMetrics,
)
from src.multimcp.retrieval.models import RankingEvent


def _ev(
    latency: float = 5.0,
    fallback_tier: int = 1,
    router_describes: list[str] | None = None,
    group: str = "control",
    active_k: int = 15,
    router_enum_size: int = 10,
) -> RankingEvent:
    return RankingEvent(
        session_id="s1",
        turn_number=0,
        catalog_version="v1",
        scorer_latency_ms=latency,
        fallback_tier=fallback_tier,
        router_describes=router_describes or [],
        group=group,
        active_k=active_k,
        router_enum_size=router_enum_size,
    )


class TestRollingMetrics:
    def test_empty_snapshot(self) -> None:
        rm = RollingMetrics()
        snap = rm.snapshot()
        assert snap.event_count == 0
        assert snap.describe_rate == 0.0
        assert snap.p95_latency_ms == 0.0

    def test_basic_metrics(self) -> None:
        rm = RollingMetrics()
        for i in range(10):
            rm.record(_ev(latency=float(i + 1)))
        snap = rm.snapshot()
        assert snap.event_count == 10
        assert snap.p50_latency_ms == pytest.approx(5.0, abs=1.0)
        assert snap.p95_latency_ms == pytest.approx(10.0, abs=1.0)

    def test_describe_rate(self) -> None:
        rm = RollingMetrics()
        rm.record(_ev(router_describes=["tool_a"]))
        rm.record(_ev(router_describes=[]))
        rm.record(_ev(router_describes=["tool_b"]))
        rm.record(_ev(router_describes=[]))
        snap = rm.snapshot()
        assert snap.describe_rate == pytest.approx(0.5, abs=0.01)

    def test_tier56_rate(self) -> None:
        rm = RollingMetrics()
        rm.record(_ev(fallback_tier=1))
        rm.record(_ev(fallback_tier=3))
        rm.record(_ev(fallback_tier=5))
        rm.record(_ev(fallback_tier=6))
        snap = rm.snapshot()
        assert snap.tier56_rate == pytest.approx(0.5, abs=0.01)

    def test_group_filter(self) -> None:
        rm = RollingMetrics()
        rm.record(_ev(group="canary", latency=10.0))
        rm.record(_ev(group="canary", latency=20.0))
        rm.record(_ev(group="control", latency=100.0))
        canary_snap = rm.snapshot(group="canary")
        assert canary_snap.event_count == 2
        assert canary_snap.p95_latency_ms <= 20.0
        control_snap = rm.snapshot(group="control")
        assert control_snap.event_count == 1

    def test_window_eviction(self) -> None:
        rm = RollingMetrics(window_seconds=1)
        rm.record(_ev(latency=100.0))
        # Manually age the event
        old_ts = rm._events[0][0] - 2
        rm._events[0] = (old_ts, rm._events[0][1])
        rm.record(_ev(latency=5.0))
        snap = rm.snapshot()
        assert snap.event_count == 1
        assert snap.p95_latency_ms == pytest.approx(5.0)

    def test_avg_active_k(self) -> None:
        rm = RollingMetrics()
        rm.record(_ev(active_k=15))
        rm.record(_ev(active_k=17))
        snap = rm.snapshot()
        assert snap.avg_active_k == pytest.approx(16.0)


class TestAlertChecker:
    def test_no_alerts_when_within_bounds(self) -> None:
        checker = AlertChecker()
        snap = MetricSnapshot(
            event_count=100,
            describe_rate=0.05,
            tier56_rate=0.02,
            p95_latency_ms=30.0,
        )
        assert checker.check(snap) == []

    def test_high_describe_rate_alert(self) -> None:
        checker = AlertChecker()
        snap = MetricSnapshot(event_count=100, describe_rate=0.15)
        alerts = checker.check(snap)
        assert any("HIGH_DESCRIBE_RATE" in a for a in alerts)

    def test_high_tier56_alert(self) -> None:
        checker = AlertChecker()
        snap = MetricSnapshot(event_count=100, tier56_rate=0.10)
        alerts = checker.check(snap)
        assert any("HIGH_TIER56_RATE" in a for a in alerts)

    def test_high_p95_alert(self) -> None:
        checker = AlertChecker()
        snap = MetricSnapshot(event_count=100, p95_latency_ms=100.0)
        alerts = checker.check(snap)
        assert any("HIGH_P95_LATENCY" in a for a in alerts)

    def test_multiple_alerts(self) -> None:
        checker = AlertChecker()
        snap = MetricSnapshot(
            event_count=100,
            describe_rate=0.20,
            tier56_rate=0.10,
            p95_latency_ms=100.0,
        )
        alerts = checker.check(snap)
        assert len(alerts) == 3

    def test_empty_events_no_alerts(self) -> None:
        checker = AlertChecker()
        snap = MetricSnapshot(event_count=0)
        assert checker.check(snap) == []

    def test_custom_thresholds(self) -> None:
        checker = AlertChecker(describe_rate=0.50, tier56_rate=0.50, p95_ms=200.0)
        snap = MetricSnapshot(
            event_count=100,
            describe_rate=0.40,
            tier56_rate=0.40,
            p95_latency_ms=150.0,
        )
        assert checker.check(snap) == []
