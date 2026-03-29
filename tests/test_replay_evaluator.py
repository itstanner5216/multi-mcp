"""Tests for offline replay evaluator (Phase 4 rollout hardening)."""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

import pytest

from src.multimcp.retrieval.models import RankingEvent
from src.multimcp.retrieval.replay import (
    GATE_P95_MS,
    GATE_TIER56_RATE,
    CutoverGate,
    ReplayMetrics,
    check_cutover_gates,
    evaluate_replay,
    format_report,
)


def _write_events(events: list[RankingEvent], path: Path) -> None:
    """Write RankingEvents as JSONL (same format as FileRetrievalLogger)."""
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(dataclasses.asdict(ev), default=str) + "\n")


def _make_event(
    session_id: str = "s1",
    turn: int = 0,
    active_k: int = 15,
    fallback_tier: int = 1,
    latency_ms: float = 5.0,
    router_describes: list[str] | None = None,
    group: str = "control",
) -> RankingEvent:
    return RankingEvent(
        session_id=session_id,
        turn_number=turn,
        catalog_version="v1",
        active_k=active_k,
        fallback_tier=fallback_tier,
        scorer_latency_ms=latency_ms,
        router_describes=router_describes or [],
        group=group,
    )


class TestEvaluateReplay:
    def test_empty_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "empty.jsonl"
        log_file.write_text("")
        metrics = evaluate_replay(log_file)
        assert metrics.total_events == 0
        assert metrics.session_count == 0

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        metrics = evaluate_replay(tmp_path / "nope.jsonl")
        assert metrics.total_events == 0

    def test_basic_metrics(self, tmp_path: Path) -> None:
        events = [
            _make_event(session_id="s1", turn=0, active_k=15, latency_ms=5.0),
            _make_event(session_id="s1", turn=1, active_k=17, latency_ms=10.0),
            _make_event(session_id="s2", turn=0, active_k=13, latency_ms=8.0),
        ]
        log_file = tmp_path / "basic.jsonl"
        _write_events(events, log_file)
        metrics = evaluate_replay(log_file)
        assert metrics.total_events == 3
        assert metrics.session_count == 2
        assert metrics.avg_active_k == pytest.approx(15.0, abs=0.1)

    def test_describe_rate(self, tmp_path: Path) -> None:
        events = [
            _make_event(router_describes=["github__search"]),
            _make_event(router_describes=[]),
            _make_event(router_describes=["brave__web_search"]),
            _make_event(router_describes=[]),
            _make_event(router_describes=[]),
        ]
        log_file = tmp_path / "describe.jsonl"
        _write_events(events, log_file)
        metrics = evaluate_replay(log_file)
        assert metrics.describe_rate == pytest.approx(0.4, abs=0.01)

    def test_tier56_rate(self, tmp_path: Path) -> None:
        events = [
            _make_event(fallback_tier=1),
            _make_event(fallback_tier=2),
            _make_event(fallback_tier=5),
            _make_event(fallback_tier=6),
            _make_event(fallback_tier=3),
        ]
        log_file = tmp_path / "tiers.jsonl"
        _write_events(events, log_file)
        metrics = evaluate_replay(log_file)
        assert metrics.tier56_rate == pytest.approx(0.4, abs=0.01)

    def test_latency_percentiles(self, tmp_path: Path) -> None:
        # 20 events with latencies 1..20
        events = [_make_event(latency_ms=float(i + 1)) for i in range(20)]
        log_file = tmp_path / "latency.jsonl"
        _write_events(events, log_file)
        metrics = evaluate_replay(log_file)
        assert metrics.p50_latency_ms == pytest.approx(10.0, abs=1.0)
        assert metrics.p95_latency_ms == pytest.approx(19.0, abs=1.0)
        assert metrics.p99_latency_ms == pytest.approx(20.0, abs=1.0)

    def test_canary_control_counts(self, tmp_path: Path) -> None:
        events = [
            _make_event(group="canary"),
            _make_event(group="canary"),
            _make_event(group="control"),
        ]
        log_file = tmp_path / "groups.jsonl"
        _write_events(events, log_file)
        metrics = evaluate_replay(log_file)
        assert metrics.canary_events == 2
        assert metrics.control_events == 1

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        log_file = tmp_path / "messy.jsonl"
        ev = _make_event()
        good_line = json.dumps(dataclasses.asdict(ev), default=str)
        log_file.write_text(f"{good_line}\nnot json\n{good_line}\n\n")
        metrics = evaluate_replay(log_file)
        assert metrics.total_events == 2


class TestCheckCutoverGates:
    def test_all_pass(self) -> None:
        metrics = ReplayMetrics(
            total_events=100,
            p95_latency_ms=30.0,
            tier56_rate=0.02,
            describe_rate=0.05,
        )
        gates = check_cutover_gates(metrics)
        assert all(g.passed for g in gates)

    def test_p95_fails(self) -> None:
        metrics = ReplayMetrics(total_events=100, p95_latency_ms=60.0, tier56_rate=0.01)
        gates = check_cutover_gates(metrics)
        p95_gate = next(g for g in gates if g.name == "p95_latency")
        assert not p95_gate.passed
        assert p95_gate.threshold == GATE_P95_MS

    def test_tier56_fails(self) -> None:
        metrics = ReplayMetrics(total_events=100, p95_latency_ms=10.0, tier56_rate=0.10)
        gates = check_cutover_gates(metrics)
        tier_gate = next(g for g in gates if g.name == "tier56_rate")
        assert not tier_gate.passed
        assert tier_gate.threshold == GATE_TIER56_RATE

    def test_describe_rate_never_fails(self) -> None:
        metrics = ReplayMetrics(total_events=100, describe_rate=0.50)
        gates = check_cutover_gates(metrics)
        desc_gate = next(g for g in gates if g.name == "describe_rate")
        assert desc_gate.passed  # Always passes (informational)

    def test_gate_actual_values(self) -> None:
        metrics = ReplayMetrics(
            total_events=100,
            p95_latency_ms=42.0,
            tier56_rate=0.03,
            describe_rate=0.08,
        )
        gates = check_cutover_gates(metrics)
        p95 = next(g for g in gates if g.name == "p95_latency")
        assert p95.actual == 42.0


class TestFormatReport:
    def test_report_contains_key_info(self) -> None:
        metrics = ReplayMetrics(total_events=50, session_count=5, p95_latency_ms=25.0)
        gates = check_cutover_gates(metrics)
        report = format_report(metrics, gates)
        assert "50" in report
        assert "25.0ms" in report
        assert "PASS" in report
