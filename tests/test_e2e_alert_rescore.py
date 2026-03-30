"""E2E test: pipeline.rebuild_catalog() calls rolling_metrics.record_rescore().

Verifies the producer→consumer path for rescore-rate monitoring:
- RetrievalPipeline receives a RollingMetrics instance
- Each rebuild_catalog() call increments rescore timestamps
- Sufficient rebuilds trigger HIGH_RESCORE_RATE alert when threshold exceeded
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.multimcp.retrieval.metrics import ALERT_RESCORE_RATE, AlertChecker, RollingMetrics
from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.session import SessionStateManager


def _make_pipeline(rolling_metrics: RollingMetrics | None = None) -> RetrievalPipeline:
    """Build a minimal RetrievalPipeline for testing."""
    config = RetrievalConfig(enabled=False)

    # Use a mock retriever (passthrough behavior sufficient for rebuild tests)
    from src.multimcp.retrieval.base import PassthroughRetriever
    from src.multimcp.retrieval.logging import NullLogger

    pipeline = RetrievalPipeline(
        retriever=PassthroughRetriever(),
        session_manager=SessionStateManager(config),
        logger=NullLogger(),
        config=config,
        tool_registry={},
        rolling_metrics=rolling_metrics,
    )
    return pipeline


class TestRebuildTriggersRecordRescore:
    """pipeline.rebuild_catalog() must call rolling_metrics.record_rescore()."""

    def test_rebuild_triggers_record_rescore(self):
        """Each rebuild_catalog() call records a rescore event on the RollingMetrics."""
        rm = RollingMetrics(window_seconds=1800)
        pipeline = _make_pipeline(rolling_metrics=rm)

        # Trigger multiple rebuilds
        for _ in range(5):
            pipeline.rebuild_catalog(pipeline.tool_registry)

        snap = rm.snapshot()
        # 5 rebuild events should produce a measurable rate
        assert snap.rescore_rate_30m > 0.0
        assert snap.rescore_rate_10m > 0.0

    def test_no_rolling_metrics_rebuild_does_not_raise(self):
        """rebuild_catalog() is safe when rolling_metrics is None (no monitoring)."""
        pipeline = _make_pipeline(rolling_metrics=None)
        # Should not raise
        pipeline.rebuild_catalog(pipeline.tool_registry)

    def test_rolling_metrics_record_rescore_called_per_rebuild(self):
        """Verify record_rescore is called exactly once per rebuild_catalog() call."""
        rm = MagicMock(spec=RollingMetrics)
        pipeline = _make_pipeline(rolling_metrics=rm)

        n_rebuilds = 3
        for _ in range(n_rebuilds):
            pipeline.rebuild_catalog(pipeline.tool_registry)

        assert rm.record_rescore.call_count == n_rebuilds

    def test_sufficient_rebuilds_produce_alert(self):
        """High-rate rebuilds (> ALERT_RESCORE_RATE/s sustained) fire an alert."""
        # ALERT_RESCORE_RATE = 0.2/s means > 1 rebuild per 5 seconds sustained.
        # We simulate by putting enough rescore events in the 10m window:
        # 0.2/s * 600s = 120 events needed in 10m window.
        rm = RollingMetrics(window_seconds=1800)
        pipeline = _make_pipeline(rolling_metrics=rm)

        # Record 130 rebuilds (> 120 threshold for the 10m window)
        for _ in range(130):
            pipeline.rebuild_catalog(pipeline.tool_registry)

        snap = rm.snapshot()
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert any("HIGH_RESCORE_RATE" in a for a in alerts), (
            f"Expected HIGH_RESCORE_RATE alert after 130 rebuilds, got: {alerts}\n"
            f"rescore_rate_10m={snap.rescore_rate_10m:.4f}, threshold={ALERT_RESCORE_RATE}"
        )

    def test_low_rebuild_rate_no_alert(self):
        """Low rebuild count does not trigger the alert."""
        rm = RollingMetrics(window_seconds=1800)
        pipeline = _make_pipeline(rolling_metrics=rm)

        # Only 5 rebuilds — well below the 120 needed for 0.2/s over 10m
        for _ in range(5):
            pipeline.rebuild_catalog(pipeline.tool_registry)

        snap = rm.snapshot()
        checker = AlertChecker()
        alerts = checker.check(snap)

        assert not any("HIGH_RESCORE_RATE" in a for a in alerts)
