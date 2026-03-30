"""Tests for Phase 9 replay cutover gates (Recall@15 and describe-rate gates).

Covers:
- Recall computation includes both direct_tool_calls and router_proxies
- Shadow group events are excluded from gate evaluation
- Gate blocks (passed=False) when either group has fewer than MIN_EVENTS_PER_GROUP events
- Describe-rate gate requires >= 20% relative drop (canary vs control)
- Describe-rate gate also blocks on insufficient data
"""

from __future__ import annotations

import pytest

from src.multimcp.retrieval.replay import (
    CutoverGate,
    MIN_EVENTS_PER_GROUP,
    ReplayMetrics,
    check_cutover_gates,
)


def _make_event(
    group: str = "canary",
    active_tool_ids: list[str] | None = None,
    direct_tool_calls: list[str] | None = None,
    router_proxies: list[str] | None = None,
    router_describes: list[str] | None = None,
) -> dict:
    return {
        "group": group,
        "active_tool_ids": active_tool_ids or [],
        "direct_tool_calls": direct_tool_calls or [],
        "router_proxies": router_proxies or [],
        "router_describes": router_describes or [],
        "scorer_latency_ms": 10.0,
        "fallback_tier": 1,
    }


def _enough_events(
    group: str,
    *,
    n: int = MIN_EVENTS_PER_GROUP,
    active: list[str] | None = None,
    direct: list[str] | None = None,
    proxied: list[str] | None = None,
    has_describe: bool = False,
) -> list[dict]:
    """Generate exactly n events for a group with given tool call pattern."""
    if active is None:
        active = ["tool_a", "tool_b"]
    if direct is None:
        direct = ["tool_a"]
    if proxied is None:
        proxied = []
    describes = ["tool_x"] if has_describe else []
    return [
        _make_event(
            group=group,
            active_tool_ids=active,
            direct_tool_calls=direct,
            router_proxies=proxied,
            router_describes=describes,
        )
        for _ in range(n)
    ]


class TestRecallGateIncludesRouterProxies:
    """router_proxies count as tool-usage events; absent from active set = recall miss."""

    def test_router_proxied_calls_counted_in_recall(self):
        """A tool retrieved via router proxy counts as a tool-usage event (recall miss)."""
        # Canary: 20 events each with 1 direct hit + 1 proxy miss
        #   direct_tool_calls=['tool_a'], router_proxies=['tool_b'], active=['tool_a']
        #   => 1 hit, 1 miss => recall = 0.5 per event => 0.5 total
        canary_evs = _enough_events(
            "canary",
            active=["tool_a"],
            direct=["tool_a"],
            proxied=["tool_b"],  # proxy miss: tool_b not in active set
        )
        # Control: 20 events with 1 direct miss each (no active tools match)
        #   direct_tool_calls=['tool_z'], active=[] => recall = 0.0
        control_evs = _enough_events(
            "control",
            active=[],
            direct=["tool_z"],  # tool_z not in active set = miss
        )
        events = canary_evs + control_evs
        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        # canary recall = 0.5 (1 hit, 1 miss per event)
        # control recall = 0.0 (all misses)
        # improvement = 0.5 - 0.0 = 0.5 >= 0.05 threshold => pass
        assert recall_gate.passed is True
        assert metrics.canary_recall == pytest.approx(0.5, abs=1e-6)
        assert metrics.control_recall == pytest.approx(0.0, abs=1e-6)

    def test_router_proxy_in_active_set_counts_as_hit(self):
        """If a router proxy target is in active_tool_ids, it counts as a hit."""
        # Edge case: proxy call where tool IS in active set (data inconsistency, but valid)
        canary_evs = _enough_events(
            "canary",
            active=["tool_a"],
            direct=[],
            proxied=["tool_a"],  # proxy but tool IS in active set => hit
        )
        control_evs = _enough_events(
            "control",
            active=[],
            direct=["tool_z"],
        )
        events = canary_evs + control_evs
        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        # canary recall = 1.0 (proxy hit), control = 0.0, improvement = 1.0 >= 0.05
        assert recall_gate.passed is True
        assert metrics.canary_recall == pytest.approx(1.0, abs=1e-6)

    def test_direct_calls_only_no_proxies(self):
        """When there are no router proxies, recall is computed from direct calls only."""
        canary_evs = _enough_events("canary", active=["tool_a"], direct=["tool_a"], proxied=[])
        control_evs = _enough_events("control", active=[], direct=["tool_z"], proxied=[])
        events = canary_evs + control_evs
        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        # canary = 1.0, control = 0.0, improvement >= 0.05 => pass
        assert recall_gate.passed is True
        assert metrics.canary_recall == pytest.approx(1.0, abs=1e-6)


class TestShadowGroupExclusion:
    """Shadow group events must be excluded from gate evaluation."""

    def test_shadow_events_excluded_from_recall(self):
        """Shadow events do not contribute to canary or control recall totals."""
        # Shadow: 50 events with only proxy misses (would tank recall if counted)
        shadow_evs = [
            _make_event("shadow", active_tool_ids=[], direct_tool_calls=[], router_proxies=["tool_z"])
            for _ in range(50)
        ]
        canary_evs = _enough_events("canary", active=["tool_a"], direct=["tool_a"])
        control_evs = _enough_events("control", active=["tool_a"], direct=["tool_a"])
        events = shadow_evs + canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        # Shadow excluded; canary = 1.0, control = 1.0, improvement = 0.0 < 0.05 => fail
        assert recall_gate.passed is False
        # Both groups should have full recall (shadow not counted)
        assert metrics.canary_recall == pytest.approx(1.0, abs=1e-6)
        assert metrics.control_recall == pytest.approx(1.0, abs=1e-6)


class TestRecallBlocksInsufficientData:
    """Gate must block with passed=False when either group has < MIN_EVENTS_PER_GROUP tool calls."""

    def test_blocks_when_canary_insufficient(self):
        """Gate fails when canary has fewer than MIN_EVENTS_PER_GROUP tool-usage events."""
        # Canary: only MIN_EVENTS_PER_GROUP - 1 events
        canary_evs = _enough_events("canary", n=MIN_EVENTS_PER_GROUP - 1)
        control_evs = _enough_events("control", n=MIN_EVENTS_PER_GROUP)
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        assert recall_gate.passed is False
        assert "Insufficient data" in recall_gate.message

    def test_blocks_when_control_insufficient(self):
        """Gate fails when control has fewer than MIN_EVENTS_PER_GROUP tool-usage events."""
        canary_evs = _enough_events("canary", n=MIN_EVENTS_PER_GROUP)
        control_evs = _enough_events("control", n=MIN_EVENTS_PER_GROUP - 1)
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        assert recall_gate.passed is False
        assert "Insufficient data" in recall_gate.message

    def test_blocks_when_both_insufficient(self):
        """Gate fails when both groups lack sufficient events."""
        canary_evs = _enough_events("canary", n=5)
        control_evs = _enough_events("control", n=5)
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        assert recall_gate.passed is False

    def test_passes_exactly_at_minimum(self):
        """Gate can evaluate when exactly MIN_EVENTS_PER_GROUP events per group."""
        # canary: all hits, control: all misses => improvement = 1.0 >= 0.05 => pass
        canary_evs = _enough_events("canary", n=MIN_EVENTS_PER_GROUP, active=["t"], direct=["t"])
        control_evs = _enough_events("control", n=MIN_EVENTS_PER_GROUP, active=[], direct=["t"])
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        recall_gate = next(g for g in gates if g.name == "recall_at_15")
        assert recall_gate.passed is True


class TestDescribeRateRelativeDrop:
    """Describe-rate gate requires >= 20% relative drop (canary vs control)."""

    def test_passes_when_canary_drop_exceeds_threshold(self):
        """20% relative drop from control to canary passes the gate."""
        # control describe rate = 0.50 (50% of events describe)
        # canary describe rate  = 0.30 (30% of events describe)
        # relative drop = (0.50 - 0.30) / 0.50 = 0.40 >= 0.20 => pass
        canary_evs = [
            _make_event("canary", router_describes=["x"] if i < 6 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        control_evs = [
            _make_event("control", router_describes=["x"] if i < 10 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        describe_gate = next(g for g in gates if g.name == "describe_rate_drop")
        assert describe_gate.passed is True

    def test_fails_when_canary_drop_below_threshold(self):
        """Less than 20% relative drop fails the gate."""
        # control describe rate = 0.50
        # canary describe rate  = 0.45
        # relative drop = (0.50 - 0.45) / 0.50 = 0.10 < 0.20 => fail
        canary_evs = [
            _make_event("canary", router_describes=["x"] if i < 9 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        control_evs = [
            _make_event("control", router_describes=["x"] if i < 10 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        describe_gate = next(g for g in gates if g.name == "describe_rate_drop")
        assert describe_gate.passed is False

    def test_fails_when_canary_higher_than_control(self):
        """Canary describe rate higher than control fails the gate."""
        canary_evs = [
            _make_event("canary", router_describes=["x"] if i < 10 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        control_evs = [
            _make_event("control", router_describes=["x"] if i < 5 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        describe_gate = next(g for g in gates if g.name == "describe_rate_drop")
        assert describe_gate.passed is False

    def test_per_group_fields_populated(self):
        """check_cutover_gates populates canary_describe_rate and control_describe_rate."""
        canary_evs = [
            _make_event("canary", router_describes=["x"] if i < 4 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        control_evs = [
            _make_event("control", router_describes=["x"] if i < 10 else [])
            for i in range(MIN_EVENTS_PER_GROUP)
        ]
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        check_cutover_gates(metrics, events=events)

        # canary: 4/20 = 0.20, control: 10/20 = 0.50
        assert metrics.canary_describe_rate == pytest.approx(0.20, abs=1e-6)
        assert metrics.control_describe_rate == pytest.approx(0.50, abs=1e-6)


class TestDescribeRateBlocksInsufficient:
    """Describe-rate gate blocks when either group has fewer than MIN_EVENTS_PER_GROUP events."""

    def test_blocks_when_canary_insufficient(self):
        canary_evs = _enough_events("canary", n=MIN_EVENTS_PER_GROUP - 1, has_describe=False)
        control_evs = _enough_events("control", n=MIN_EVENTS_PER_GROUP, has_describe=True)
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        describe_gate = next(g for g in gates if g.name == "describe_rate_drop")
        assert describe_gate.passed is False
        assert "Insufficient data" in describe_gate.message

    def test_blocks_when_control_insufficient(self):
        canary_evs = _enough_events("canary", n=MIN_EVENTS_PER_GROUP, has_describe=False)
        control_evs = _enough_events("control", n=MIN_EVENTS_PER_GROUP - 1, has_describe=True)
        events = canary_evs + control_evs

        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=events)

        describe_gate = next(g for g in gates if g.name == "describe_rate_drop")
        assert describe_gate.passed is False

    def test_no_events_provided_uses_legacy_path(self):
        """When events=None (legacy path), describe_rate gate is informational (passed=True)."""
        metrics = ReplayMetrics(describe_rate=0.50)
        gates = check_cutover_gates(metrics, events=None)

        describe_gate = next(g for g in gates if "describe" in g.name)
        assert describe_gate.passed is True  # informational only in legacy path
