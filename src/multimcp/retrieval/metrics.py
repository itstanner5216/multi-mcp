"""Rolling metric aggregation and alert checking for BMXF rollout monitoring.

RollingMetrics maintains a sliding window of RankingEvents and computes
real-time metrics. AlertChecker evaluates metrics against configured
thresholds and returns triggered alert messages.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import RankingEvent


@dataclass
class MetricSnapshot:
    """Point-in-time metric values computed from the rolling window."""

    event_count: int = 0
    describe_rate: float = 0.0
    tier56_rate: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_active_k: float = 0.0
    avg_router_enum_size: float = 0.0
    # Phase 9: rescore-rate fields for ALERT_RESCORE_RATE monitoring
    rescore_rate_30m: float = 0.0   # rescores per second in last 30 minutes
    rescore_rate_10m: float = 0.0   # rescores per second in last 10 minutes (alert trigger)


class RollingMetrics:
    """Sliding-window metric aggregation over RankingEvents.

    Events older than window_seconds are automatically evicted on each
    record() call. Use snapshot() to get current computed metrics.

    Phase 9 addition: record_rescore() tracks catalog rebuild events
    separately from RankingEvents. rescore_rate_10m and rescore_rate_30m
    are exposed via snapshot() for use by AlertChecker.
    """

    def __init__(self, window_seconds: int = 1800) -> None:
        self._window = window_seconds
        self._events: deque[tuple[float, "RankingEvent"]] = deque()
        # Phase 9: separate deque for rescore timestamps (catalog rebuild events)
        # Stores monotonic timestamps only — no payload needed.
        self._rescore_times: deque[float] = deque()

    def record(self, event: "RankingEvent") -> None:
        """Add a RankingEvent to the window."""
        now = time.monotonic()
        self._events.append((now, event))
        self._evict(now)

    def record_rescore(self) -> None:
        """Record a catalog rebuild (rescore) event.

        Called by RetrievalPipeline.rebuild_catalog() after each rebuild.
        Timestamps are used to compute rescore_rate_10m and rescore_rate_30m
        in snapshot(), which drives the ALERT_RESCORE_RATE check.
        """
        now = time.monotonic()
        self._rescore_times.append(now)
        # Evict rescore timestamps outside the 30-minute window
        cutoff = now - self._window
        while self._rescore_times and self._rescore_times[0] < cutoff:
            self._rescore_times.popleft()

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def snapshot(self, group: str | None = None) -> MetricSnapshot:
        """Compute current metrics, optionally filtered by group.

        Args:
            group: If set, only include events matching this group ("canary" or "control").
        """
        now = time.monotonic()
        self._evict(now)

        events = [
            ev for _, ev in self._events
            if group is None or getattr(ev, "group", "control") == group
        ]

        if not events:
            snap = MetricSnapshot()
        else:
            total = len(events)
            describe_count = sum(
                1 for ev in events if getattr(ev, "router_describes", None) and len(ev.router_describes) > 0
            )
            tier56_count = sum(
                1 for ev in events if getattr(ev, "fallback_tier", 1) >= 5
            )

            latencies = sorted(getattr(ev, "scorer_latency_ms", 0.0) for ev in events)

            def pct(sorted_vals: list[float], p: float) -> float:
                if not sorted_vals:
                    return 0.0
                idx = min(int(p * len(sorted_vals)), len(sorted_vals) - 1)
                return sorted_vals[idx]

            total_k = sum(getattr(ev, "active_k", 0) for ev in events)
            total_enum = sum(getattr(ev, "router_enum_size", 0) for ev in events)

            snap = MetricSnapshot(
                event_count=total,
                describe_rate=describe_count / total,
                tier56_rate=tier56_count / total,
                p50_latency_ms=pct(latencies, 0.50),
                p95_latency_ms=pct(latencies, 0.95),
                p99_latency_ms=pct(latencies, 0.99),
                avg_active_k=total_k / total,
                avg_router_enum_size=total_enum / total,
            )

        # Phase 9: rescore-rate computation from timestamp deque.
        # rescore_rate_30m: all events in window / window_seconds
        # rescore_rate_10m: events in last 600s / 600s (alert trigger window),
        # but constrained by the configured rolling window to avoid understating the rate
        ten_min_window = min(600.0, self._window)
        ten_min_cutoff = now - ten_min_window
        rescore_count_10m = sum(1 for t in self._rescore_times if t >= ten_min_cutoff)
        snap.rescore_rate_30m = len(self._rescore_times) / self._window if self._rescore_times else 0.0
        snap.rescore_rate_10m = rescore_count_10m / ten_min_window if rescore_count_10m > 0 else 0.0

        return snap


# ── Alert thresholds ─────────────────────────────────────────────────────
# From ROADMAP.md Phase 4 and synthesized plan section 12.
ALERT_DESCRIBE_RATE = 0.10   # > 10% describe rate
ALERT_TIER56_RATE = 0.05     # > 5% at Tier 5-6
ALERT_P95_MS = 75.0          # > 75ms p95 latency
ALERT_RESCORE_RATE = 0.2     # > 1 rescore per 5 seconds (0.2/s)


class AlertChecker:
    """Evaluate metrics against alert thresholds.

    Returns a list of triggered alert messages. Empty list = all clear.

    Phase 9: rescore_threshold parameter added so the ALERT_RESCORE_RATE
    check is wired into check() rather than defined-but-unused.
    """

    def __init__(
        self,
        describe_rate: float = ALERT_DESCRIBE_RATE,
        tier56_rate: float = ALERT_TIER56_RATE,
        p95_ms: float = ALERT_P95_MS,
        rescore_threshold: float = ALERT_RESCORE_RATE,
    ) -> None:
        self._describe_rate = describe_rate
        self._tier56_rate = tier56_rate
        self._p95_ms = p95_ms
        self._rescore_threshold = rescore_threshold

    def check(self, snapshot: MetricSnapshot) -> list[str]:
        """Check snapshot against thresholds. Returns list of alert messages."""
        alerts: list[str] = []

        if snapshot.event_count == 0 and snapshot.rescore_rate_10m == 0.0:
            return alerts

        if snapshot.describe_rate > self._describe_rate:
            alerts.append(
                f"HIGH_DESCRIBE_RATE: {snapshot.describe_rate:.1%} > {self._describe_rate:.0%}"
            )

        if snapshot.tier56_rate > self._tier56_rate:
            alerts.append(
                f"HIGH_TIER56_RATE: {snapshot.tier56_rate:.1%} > {self._tier56_rate:.0%}"
            )

        if snapshot.p95_latency_ms > self._p95_ms:
            alerts.append(
                f"HIGH_P95_LATENCY: {snapshot.p95_latency_ms:.1f}ms > {self._p95_ms:.0f}ms"
            )

        # Phase 9: Rescore-rate alert — fires only on rescore_rate_10m exceeding
        # threshold. The 30-minute average alone does not trigger the alert.
        # Source: synthesized plan line 961: ">1/5s sustained for 10min"
        if snapshot.rescore_rate_10m > self._rescore_threshold:
            alerts.append(
                f"HIGH_RESCORE_RATE: {snapshot.rescore_rate_10m:.2f}/s > {self._rescore_threshold:.1f}/s (10m window)"
            )

        return alerts
