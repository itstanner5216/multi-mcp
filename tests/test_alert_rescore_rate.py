"""Tests for Phase 9 ALERT_RESCORE_RATE monitoring.

Covers:
- rescore_rate_10m > 0.2 fires HIGH_RESCORE_RATE alert
- 30-minute average alone (rescore_rate_30m > 0.2 but rescore_rate_10m <= 0.2) does NOT fire
- AlertChecker accepts configurable rescore_threshold
- rescore_rate_10m = 0.0 with event_count = 0 short-circuits (no alerts)
"""

from __future__ import annotations

import time

import pytest

from src.multimcp.retrieval.metrics import (
    ALERT_RESCORE_RATE,
    AlertChecker,
    MetricSnapshot,
    RollingMetrics,
)


class TestRescoreAlertFires:
    """HIGH_RESCORE_RATE alert fires when rescore_rate_10m exceeds threshold."""

    def test_rescore_alert_sustained_10m(self):
        """rescore_rate_10m > 0.2 triggers HIGH_RESCORE_RATE alert."""
        snap = MetricSnapshot(
            event_count=0,
            rescore_rate_10m=0.3,   # > 0.2 threshold
            rescore_rate_30m=0.3,
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert any("HIGH_RESCORE_RATE" in a for a in alerts), (
            f"Expected HIGH_RESCORE_RATE alert, got: {alerts}"
        )

    def test_alert_message_includes_rate_and_threshold(self):
        """Alert message includes actual rate and threshold for operator visibility."""
        snap = MetricSnapshot(
            event_count=0,
            rescore_rate_10m=0.5,
            rescore_rate_30m=0.5,
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        rescore_alerts = [a for a in alerts if "HIGH_RESCORE_RATE" in a]
        assert len(rescore_alerts) == 1
        assert "0.50" in rescore_alerts[0] or "0.5" in rescore_alerts[0]
        assert "(10m window)" in rescore_alerts[0]

    def test_rescore_alert_at_exact_threshold_does_not_fire(self):
        """Rate exactly at threshold (== 0.2) does NOT fire alert (strictly greater than)."""
        snap = MetricSnapshot(
            event_count=0,
            rescore_rate_10m=ALERT_RESCORE_RATE,  # exactly 0.2
            rescore_rate_30m=ALERT_RESCORE_RATE,
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert not any("HIGH_RESCORE_RATE" in a for a in alerts)

    def test_rescore_alert_just_above_threshold_fires(self):
        """Rate just above threshold fires alert."""
        snap = MetricSnapshot(
            event_count=0,
            rescore_rate_10m=ALERT_RESCORE_RATE + 0.001,
            rescore_rate_30m=ALERT_RESCORE_RATE + 0.001,
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert any("HIGH_RESCORE_RATE" in a for a in alerts)


class TestRescoreAlertNot30mOnly:
    """30-minute average alone does NOT trigger the rescore-rate alert."""

    def test_high_30m_rate_but_low_10m_does_not_fire(self):
        """rescore_rate_30m > 0.2 but rescore_rate_10m <= 0.2 → no alert."""
        snap = MetricSnapshot(
            event_count=0,
            rescore_rate_30m=0.5,   # high 30m rate
            rescore_rate_10m=0.1,   # but low 10m rate (not sustained)
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert not any("HIGH_RESCORE_RATE" in a for a in alerts), (
            f"30m-only rate should not trigger alert, got: {alerts}"
        )

    def test_zero_10m_rate_never_fires(self):
        """rescore_rate_10m = 0.0 never fires the alert regardless of 30m rate."""
        snap = MetricSnapshot(
            event_count=10,
            rescore_rate_30m=1.0,   # extreme 30m rate
            rescore_rate_10m=0.0,   # but no activity in last 10m
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert not any("HIGH_RESCORE_RATE" in a for a in alerts)


class TestRollingMetricsRescore:
    """RollingMetrics.record_rescore() tracks rescore events and exposes rates in snapshot()."""

    def test_record_rescore_increments_snapshot_rates(self):
        """After recording rescores, snapshot shows non-zero rescore rates."""
        rm = RollingMetrics(window_seconds=1800)
        for _ in range(10):
            rm.record_rescore()
        snap = rm.snapshot()

        assert snap.rescore_rate_30m > 0.0
        assert snap.rescore_rate_10m > 0.0

    def test_rescore_rate_30m_computation(self):
        """rescore_rate_30m = count_in_window / window_seconds."""
        rm = RollingMetrics(window_seconds=1800)
        n = 9
        for _ in range(n):
            rm.record_rescore()
        snap = rm.snapshot()

        # All n events are within the 30m window
        assert snap.rescore_rate_30m == pytest.approx(n / 1800.0, abs=1e-6)

    def test_rescore_rate_10m_computation(self):
        """rescore_rate_10m = events in last 600s / 600s."""
        rm = RollingMetrics(window_seconds=1800)
        n = 6
        for _ in range(n):
            rm.record_rescore()
        snap = rm.snapshot()

        # All events occurred just now (within last 10m)
        assert snap.rescore_rate_10m == pytest.approx(n / 600.0, abs=1e-6)

    def test_no_rescores_gives_zero_rates(self):
        """No rescore events recorded → both rates are 0.0."""
        rm = RollingMetrics(window_seconds=1800)
        snap = rm.snapshot()

        assert snap.rescore_rate_30m == 0.0
        assert snap.rescore_rate_10m == 0.0


class TestAlertCheckerEarlyReturn:
    """AlertChecker.check() early-return must not suppress rescore alerts."""

    def test_early_return_blocked_when_rescore_rate_nonzero(self):
        """When event_count=0 but rescore_rate_10m > 0, alerts still fire."""
        snap = MetricSnapshot(
            event_count=0,         # no ranking events
            rescore_rate_10m=0.5,  # but rescores are happening
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert any("HIGH_RESCORE_RATE" in a for a in alerts)

    def test_both_zero_returns_empty(self):
        """event_count=0 AND rescore_rate_10m=0.0 → empty alerts (short-circuit)."""
        snap = MetricSnapshot(
            event_count=0,
            rescore_rate_10m=0.0,
        )
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert alerts == []


class TestAlertCheckerCustomThreshold:
    """AlertChecker accepts configurable rescore_threshold."""

    def test_custom_threshold_respected(self):
        """Custom rescore_threshold overrides ALERT_RESCORE_RATE default."""
        checker = AlertChecker(rescore_threshold=0.5)
        # Below custom threshold: no alert
        snap_low = MetricSnapshot(event_count=0, rescore_rate_10m=0.3)
        assert not any("HIGH_RESCORE_RATE" in a for a in checker.check(snap_low))

        # Above custom threshold: alert
        snap_high = MetricSnapshot(event_count=0, rescore_rate_10m=0.6)
        assert any("HIGH_RESCORE_RATE" in a for a in checker.check(snap_high))
