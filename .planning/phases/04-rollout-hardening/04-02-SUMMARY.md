---
phase: 04-rollout-hardening
plan: "02"
subsystem: retrieval
tags: [replay, metrics, cutover-gates, rollout, bmxf, observability]
dependency_graph:
  requires:
    - src/multimcp/retrieval/models.py (RankingEvent, group field)
    - src/multimcp/retrieval/logging.py (FileRetrievalLogger JSONL format)
  provides:
    - src/multimcp/retrieval/replay.py (offline replay evaluator)
    - tests/test_replay_evaluator.py (14 tests)
  affects:
    - Phase 4 cutover decisions (p95, tier56 gates)
tech_stack:
  added: []
  patterns:
    - JSONL parsing with graceful skip of malformed lines
    - Percentile computation via sorted-list index formula
    - Dataclass-based gate reporting with pass/fail fields
key_files:
  created:
    - src/multimcp/retrieval/replay.py
    - tests/test_replay_evaluator.py
  modified: []
decisions:
  - describe_rate gate is informational-only (always passed=True) per ROADMAP.md Phase 4 spec
  - p95 percentile uses int(0.95 * n) index formula (consistent with plan spec)
  - Malformed JSONL lines silently skipped for robustness
metrics:
  duration: "2m 15s"
  completed: "2026-03-29T18:13:03Z"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
  tests_added: 14
  tests_total: 932
---

# Phase 4 Plan 02: Offline Replay Evaluator Summary

**One-liner:** Offline JSONL replay evaluator with p95/tier56 cutover gates for BMXF rollout gate-keeping.

## What Was Built

Created `src/multimcp/retrieval/replay.py` — the measurement backbone for Phase 4 rollout decisions. This module reads `RankingEvent` JSONL logs produced by `FileRetrievalLogger` and computes aggregated rollout metrics, then evaluates pass/fail against cutover gates.

### Key Exports

- `ReplayMetrics`: dataclass with `total_events`, `session_count`, `avg_active_k`, `describe_rate`, `tier56_rate`, `p50/p95/p99_latency_ms`, `avg_alpha`, `avg_router_enum_size`, `canary_events`, `control_events`
- `CutoverGate`: dataclass with `name`, `passed`, `threshold`, `actual`, `message`
- `evaluate_replay(log_path)`: reads JSONL, skips malformed lines, returns `ReplayMetrics`
- `check_cutover_gates(metrics)`: returns 3 gates — p95 latency (hard), tier56 rate (hard), describe rate (informational)
- `format_report(metrics, gates)`: human-readable report for stdout
- `main()`: CLI entry — `python -m src.multimcp.retrieval.replay <path>`

### Cutover Gate Thresholds

| Gate | Threshold | Type |
|------|-----------|------|
| p95_latency | < 50ms | Hard (FAIL blocks GA) |
| tier56_rate | < 5% | Hard (FAIL blocks GA) |
| describe_rate | informational | Always PASS, warns if > 10% |

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create replay.py with ReplayMetrics, evaluate_replay(), check_cutover_gates() | a43f4ad | src/multimcp/retrieval/replay.py |
| 2 | Create tests/test_replay_evaluator.py | 01a0684 | tests/test_replay_evaluator.py |

## Test Results

- 14 new tests added in `tests/test_replay_evaluator.py`
- 932 total tests passing (0 regressions)
- Test classes: `TestEvaluateReplay` (8 tests), `TestCheckCutoverGates` (5 tests), `TestFormatReport` (1 test)

## Deviations from Plan

None — plan executed exactly as written.

**Note on `group` field:** The plan states the `group` field is added to `RankingEvent` "after 04-01". The 04-01 plan (running in parallel) had already added `group: str = "control"` to `RankingEvent` in the working tree, so tests constructing `RankingEvent` with `group=` parameter worked correctly. No additional action was needed.

## Known Stubs

None.

## Self-Check: PASSED

- `src/multimcp/retrieval/replay.py` — FOUND
- `tests/test_replay_evaluator.py` — FOUND
- Commit a43f4ad — FOUND
- Commit 01a0684 — FOUND
- 14 tests pass — VERIFIED
- 932 total tests pass — VERIFIED
