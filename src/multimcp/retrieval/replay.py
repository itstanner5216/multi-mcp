"""Offline replay evaluator for RankingEvent JSONL logs.

Reads logs produced by FileRetrievalLogger, computes rollout metrics,
and checks cutover gates for shadow -> canary -> GA transitions.

Usage:
    python -m src.multimcp.retrieval.replay path/to/ranking_events.jsonl
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReplayMetrics:
    """Aggregated metrics from a RankingEvent JSONL log file."""

    total_events: int = 0
    session_count: int = 0
    avg_active_k: float = 0.0
    describe_rate: float = 0.0       # fraction of turns with router_describes > 0
    tier56_rate: float = 0.0         # fraction of events at fallback tier >= 5
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_alpha: float = 0.0
    avg_router_enum_size: float = 0.0
    canary_events: int = 0
    control_events: int = 0
    # Phase 9: per-group recall metrics for cutover-gate evaluation
    recall_at_15: float = 0.0           # canary-side headline recall metric
    canary_recall: float = 0.0          # recall for canary group (excluding shadow)
    control_recall: float = 0.0         # recall for control group (excluding shadow)
    canary_describe_rate: float = 0.0   # describe rate for canary group
    control_describe_rate: float = 0.0  # describe rate for control group


@dataclass
class CutoverGate:
    """Result of a single cutover gate check."""

    name: str
    passed: bool
    threshold: float
    actual: float
    message: str


def evaluate_replay(log_path: str | Path) -> ReplayMetrics:
    """Read JSONL RankingEvents and compute aggregated metrics.

    Each line in the file must be a JSON object with RankingEvent fields.
    Malformed lines are silently skipped.
    """
    path = Path(log_path)
    if not path.exists():
        return ReplayMetrics()

    events: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not events:
        return ReplayMetrics()

    total = len(events)
    sessions: set[str] = set()
    latencies: list[float] = []
    describe_count = 0
    tier56_count = 0
    total_active_k = 0
    total_alpha = 0.0
    total_router_enum = 0
    canary_count = 0
    control_count = 0

    for ev in events:
        sessions.add(ev.get("session_id", ""))
        latency = ev.get("scorer_latency_ms", 0.0)
        latencies.append(float(latency))
        total_active_k += int(ev.get("active_k", 0))
        total_alpha += float(ev.get("alpha", 0.0))
        total_router_enum += int(ev.get("router_enum_size", 0))

        describes = ev.get("router_describes", [])
        if describes and len(describes) > 0:
            describe_count += 1

        tier = int(ev.get("fallback_tier", 1))
        if tier >= 5:
            tier56_count += 1

        group = ev.get("group", "control")
        if group == "canary":
            canary_count += 1
        elif group != "shadow":
            control_count += 1

    latencies.sort()

    def percentile(sorted_vals: list[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        idx = min(int(pct * len(sorted_vals)), len(sorted_vals) - 1)
        return sorted_vals[idx]

    return ReplayMetrics(
        total_events=total,
        session_count=len(sessions),
        avg_active_k=total_active_k / total if total else 0.0,
        describe_rate=describe_count / total if total else 0.0,
        tier56_rate=tier56_count / total if total else 0.0,
        p50_latency_ms=percentile(latencies, 0.50),
        p95_latency_ms=percentile(latencies, 0.95),
        p99_latency_ms=percentile(latencies, 0.99),
        avg_alpha=total_alpha / total if total else 0.0,
        avg_router_enum_size=total_router_enum / total if total else 0.0,
        canary_events=canary_count,
        control_events=control_count,
    )


# ── Cutover gate thresholds ──────────────────────────────────────────────
# From ROADMAP.md Phase 4 success criteria and synthesized plan section 13.
GATE_P95_MS = 50.0              # p95 scoring latency must be < 50ms
GATE_TIER56_RATE = 0.05         # Tier 5-6 must be < 5% of events

# Phase 9 recall and describe-rate gate thresholds (source plan Section 4-5)
MIN_EVENTS_PER_GROUP = 20       # Minimum events per group before gate can evaluate
GATE_RECALL_IMPROVEMENT = 0.05  # Canary recall improvement over control must be >= 5%
GATE_DESCRIBE_DROP = 0.20       # Canary describe rate must drop >= 20% relative to control


def _compute_group_recall(group_events: list[dict]) -> tuple[float, int]:
    """Compute recall@K for a group of JSONL events.

    Recall is measured as: of all tool-usage events (direct_tool_calls +
    router_proxies), what fraction used a tool that was in the active set?

    A router-proxied call means the tool was absent from the active set
    at the time of use (recall miss), unless explicit active_tool_ids data
    shows the tool present.

    Returns:
        (recall, total_tool_usage_count)
    """
    total = 0
    hits = 0
    for ev in group_events:
        active_tools = set(ev.get("active_tool_ids", []))
        # Direct calls: tool was in active set = hit
        for call in ev.get("direct_tool_calls", []):
            total += 1
            if call in active_tools:
                hits += 1
        # Router-proxied calls: tool was NOT in active set at time of use.
        # This is a recall miss unless active_tool_ids explicitly shows the
        # tool as present (which would indicate a data recording inconsistency).
        for proxy_call in ev.get("router_proxies", []):
            total += 1
            if proxy_call in active_tools:
                # Explicit active membership takes precedence (data inconsistency
                # case — treat as hit, but this should be rare/impossible in
                # well-formed logs).
                hits += 1
            # else: router proxy = tool not in active set = recall miss (no increment)
    recall = hits / total if total > 0 else 0.0
    return recall, total


def _compute_describe_rate(group_events: list[dict]) -> float:
    """Compute describe rate for a group: fraction of events with router_describes > 0."""
    if not group_events:
        return 0.0
    describe_count = sum(
        1 for ev in group_events
        if ev.get("router_describes") and len(ev["router_describes"]) > 0
    )
    return describe_count / len(group_events)


def check_cutover_gates(metrics: ReplayMetrics, events: list[dict] | None = None) -> list[CutoverGate]:
    """Check whether metrics pass the cutover gates for GA promotion.

    Returns a list of CutoverGate results. All gates must pass for
    the rollout to proceed from canary to GA.

    Args:
        metrics: Pre-computed ReplayMetrics (used for latency/tier56 gates and
                 for populating per-group recall/describe fields).
        events: Raw event list for per-group gate computation. If None, the
                recall_at_15 and describe_rate gates use pre-populated fields
                on metrics (e.g., from evaluate_replay_with_gates).
    """
    gates: list[CutoverGate] = []

    # Gate 1: p95 latency
    p95_pass = metrics.p95_latency_ms < GATE_P95_MS
    gates.append(CutoverGate(
        name="p95_latency",
        passed=p95_pass,
        threshold=GATE_P95_MS,
        actual=metrics.p95_latency_ms,
        message=f"p95 latency {metrics.p95_latency_ms:.1f}ms {'<' if p95_pass else '>='} {GATE_P95_MS}ms",
    ))

    # Gate 2: Tier 5-6 rate
    tier_pass = metrics.tier56_rate < GATE_TIER56_RATE
    gates.append(CutoverGate(
        name="tier56_rate",
        passed=tier_pass,
        threshold=GATE_TIER56_RATE,
        actual=metrics.tier56_rate,
        message=f"Tier 5-6 rate {metrics.tier56_rate:.1%} {'<' if tier_pass else '>='} {GATE_TIER56_RATE:.0%}",
    ))

    if events is not None:
        # ── Gate 3: Recall@15 (Phase 9) ────────────────────────────────────────
        # Exclude shadow-group events. Compute canary and control separately.
        # Require at least MIN_EVENTS_PER_GROUP tool-usage events per group.
        non_shadow = [ev for ev in events if ev.get("group") != "shadow"]
        canary_evs = [ev for ev in non_shadow if ev.get("group") == "canary"]
        control_evs = [ev for ev in non_shadow if ev.get("group") == "control"]

        canary_recall, canary_total = _compute_group_recall(canary_evs)
        control_recall, control_total = _compute_group_recall(control_evs)

        # Populate per-group fields on metrics for reporting
        metrics.canary_recall = canary_recall
        metrics.control_recall = control_recall
        metrics.recall_at_15 = canary_recall  # headline metric is canary-side

        if canary_total < MIN_EVENTS_PER_GROUP or control_total < MIN_EVENTS_PER_GROUP:
            gates.append(CutoverGate(
                name="recall_at_15",
                passed=False,
                threshold=GATE_RECALL_IMPROVEMENT,
                actual=0.0,
                message=(
                    f"Insufficient data: canary={canary_total}, control={control_total}, "
                    f"need {MIN_EVENTS_PER_GROUP} per group"
                ),
            ))
        else:
            recall_improvement = canary_recall - control_recall
            recall_pass = recall_improvement >= GATE_RECALL_IMPROVEMENT
            gates.append(CutoverGate(
                name="recall_at_15",
                passed=recall_pass,
                threshold=GATE_RECALL_IMPROVEMENT,
                actual=recall_improvement,
                message=(
                    f"Recall@15 improvement {recall_improvement:.1%} "
                    f"{'>=5%' if recall_pass else '<5%'} "
                    f"(canary={canary_recall:.1%}, control={control_recall:.1%})"
                ),
            ))

        # ── Gate 4: Describe-rate relative drop (Phase 9) ──────────────────────
        # Canary describe rate must be at least 20% lower than control (relative).
        # Excludes shadow events. Requires >= MIN_EVENTS_PER_GROUP per group.
        canary_describe = _compute_describe_rate(canary_evs)
        control_describe = _compute_describe_rate(control_evs)

        # Populate fields on metrics for reporting
        metrics.canary_describe_rate = canary_describe
        metrics.control_describe_rate = control_describe

        canary_n = len(canary_evs)
        control_n = len(control_evs)

        if canary_n < MIN_EVENTS_PER_GROUP or control_n < MIN_EVENTS_PER_GROUP:
            gates.append(CutoverGate(
                name="describe_rate_drop",
                passed=False,
                threshold=GATE_DESCRIBE_DROP,
                actual=0.0,
                message=(
                    f"Insufficient data: canary={canary_n}, control={control_n}, "
                    f"need {MIN_EVENTS_PER_GROUP} per group"
                ),
            ))
        else:
            # Relative drop: (control - canary) / control
            if control_describe > 0:
                describe_drop = (control_describe - canary_describe) / control_describe
            else:
                # Control has zero describe rate: canary can only match (0.0) or be worse
                describe_drop = 0.0 if canary_describe == 0 else -1.0
            describe_pass = describe_drop >= GATE_DESCRIBE_DROP
            gates.append(CutoverGate(
                name="describe_rate_drop",
                passed=describe_pass,
                threshold=GATE_DESCRIBE_DROP,
                actual=describe_drop,
                message=(
                    f"Describe rate drop {describe_drop:.1%} "
                    f"{'>=20%' if describe_pass else '<20%'} "
                    f"(canary={canary_describe:.1%}, control={control_describe:.1%})"
                ),
            ))
    else:
        # No raw events provided: emit informational describe-rate gate from
        # pre-populated metrics fields (legacy path — no per-group computation)
        describe_warn = metrics.describe_rate > 0.10
        gates.append(CutoverGate(
            name="describe_rate",
            passed=True,  # Informational only when no events provided
            threshold=0.10,
            actual=metrics.describe_rate,
            message=f"Describe rate {metrics.describe_rate:.1%}"
            + (f" WARNING: exceeds 10%" if describe_warn else " OK"),
        ))

    return gates


def evaluate_replay_with_gates(
    log_path: str | Path,
) -> tuple[ReplayMetrics, list[CutoverGate]]:
    """Convenience function: load JSONL log, compute metrics and check all gates.

    Returns (metrics, gates). Per-group fields (canary_recall, control_recall,
    canary_describe_rate, control_describe_rate, recall_at_15) are populated
    on metrics as a side-effect of gate computation.
    """
    path = Path(log_path)
    if not path.exists():
        metrics = ReplayMetrics()
        gates = check_cutover_gates(metrics, events=[])
        return metrics, gates

    events_raw: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events_raw.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    metrics = evaluate_replay(log_path)
    gates = check_cutover_gates(metrics, events=events_raw)
    return metrics, gates


def format_report(metrics: ReplayMetrics, gates: list[CutoverGate]) -> str:
    """Format a human-readable report from metrics and gates."""
    lines = [
        "=" * 60,
        "  BMXF Rollout Replay Report",
        "=" * 60,
        "",
        f"  Events:        {metrics.total_events}",
        f"  Sessions:      {metrics.session_count}",
        f"  Canary events: {metrics.canary_events}",
        f"  Control events:{metrics.control_events}",
        "",
        f"  Avg active K:  {metrics.avg_active_k:.1f}",
        f"  Avg alpha:     {metrics.avg_alpha:.3f}",
        f"  Router enum:   {metrics.avg_router_enum_size:.1f} avg",
        "",
        "  Latency:",
        f"    p50:  {metrics.p50_latency_ms:.1f}ms",
        f"    p95:  {metrics.p95_latency_ms:.1f}ms",
        f"    p99:  {metrics.p99_latency_ms:.1f}ms",
        "",
        f"  Describe rate: {metrics.describe_rate:.1%}",
        f"  Tier 5-6 rate: {metrics.tier56_rate:.1%}",
    ]

    # Phase 9: per-group metrics (only shown when non-zero / computed)
    if metrics.canary_recall > 0 or metrics.control_recall > 0 or metrics.recall_at_15 > 0:
        lines += [
            "",
            "  Per-Group Recall (Phase 9 Gates):",
            f"    Canary recall:   {metrics.canary_recall:.1%}",
            f"    Control recall:  {metrics.control_recall:.1%}",
            f"    Recall@15:       {metrics.recall_at_15:.1%}  (canary headline)",
        ]

    if metrics.canary_describe_rate > 0 or metrics.control_describe_rate > 0:
        lines += [
            "",
            "  Per-Group Describe Rate:",
            f"    Canary:   {metrics.canary_describe_rate:.1%}",
            f"    Control:  {metrics.control_describe_rate:.1%}",
        ]

    lines += [
        "",
        "-" * 60,
        "  Cutover Gates:",
        "-" * 60,
    ]

    all_pass = True
    for g in gates:
        status = "PASS" if g.passed else "FAIL"
        lines.append(f"  [{status}] {g.message}")
        if not g.passed:
            all_pass = False

    lines.append("")
    lines.append(f"  Overall: {'ALL GATES PASS' if all_pass else 'BLOCKED -- fix failing gates'}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> None:
    """CLI entry point: evaluate a JSONL log file and print report."""
    if len(sys.argv) < 2:
        print(f"Usage: python -m src.multimcp.retrieval.replay <log_path>", file=sys.stderr)
        sys.exit(1)
    log_path = sys.argv[1]
    metrics, gates = evaluate_replay_with_gates(log_path)
    print(format_report(metrics, gates))
    if not all(g.passed for g in gates):
        sys.exit(1)


if __name__ == "__main__":
    main()
