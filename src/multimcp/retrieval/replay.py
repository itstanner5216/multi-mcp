"""Offline replay evaluator for RankingEvent JSONL logs.

Reads logs produced by FileRetrievalLogger, computes rollout metrics,
and checks cutover gates for shadow -> canary -> GA transitions.

Usage:
    python -m src.multimcp.retrieval.replay path/to/ranking_events.jsonl
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
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
        else:
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
GATE_P95_MS = 50.0          # p95 scoring latency must be < 50ms
GATE_TIER56_RATE = 0.05     # Tier 5-6 must be < 5% of events
GATE_DESCRIBE_RATE = 0.10   # Informational: describe rate > 10% is a warning


def check_cutover_gates(metrics: ReplayMetrics) -> list[CutoverGate]:
    """Check whether metrics pass the cutover gates for GA promotion.

    Returns a list of CutoverGate results. All gates must pass for
    the rollout to proceed from canary to GA.
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

    # Gate 3: Describe rate (informational — always passes but warns)
    describe_warn = metrics.describe_rate > GATE_DESCRIBE_RATE
    gates.append(CutoverGate(
        name="describe_rate",
        passed=True,  # Informational only
        threshold=GATE_DESCRIBE_RATE,
        actual=metrics.describe_rate,
        message=f"Describe rate {metrics.describe_rate:.1%}"
        + (f" WARNING: exceeds {GATE_DESCRIBE_RATE:.0%}" if describe_warn else " OK"),
    ))

    return gates


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
    metrics = evaluate_replay(log_path)
    gates = check_cutover_gates(metrics)
    print(format_report(metrics, gates))
    if not all(g.passed for g in gates):
        sys.exit(1)


if __name__ == "__main__":
    main()
