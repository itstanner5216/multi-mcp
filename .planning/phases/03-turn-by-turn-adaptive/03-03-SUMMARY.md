---
phase: 03-turn-by-turn-adaptive
plan: "03"
subsystem: telemetry
tags: [monitor, adaptive-polling, significance-threshold, debounce, tdd]
dependency_graph:
  requires:
    - "03-turn-by-turn-adaptive/03-01 (RRF fusion, TurnContext)"
    - "02-safe-lexical-mvp/02-01 (telemetry scanner, WorkspaceEvidence)"
  provides:
    - "RootMonitor with adaptive polling (5s->10s->20s->30s)"
    - "Cumulative significance threshold (>=0.7 triggers re-score)"
    - "Debounce mechanism (min_debounce_s prevents back-to-back triggers)"
  affects:
    - "src/multimcp/retrieval/telemetry/__init__.py (new export)"
tech_stack:
  added: []
  patterns:
    - "Adaptive backoff via poll schedule index (backs off after 2 idle polls)"
    - "Cumulative significance accumulation in record_change()"
    - "Debounce via monotonic timer comparison in check_for_changes()"
    - "TDD: RED tests committed before GREEN implementation"
key_files:
  created:
    - src/multimcp/retrieval/telemetry/monitor.py
    - tests/test_telemetry_monitor.py
  modified:
    - src/multimcp/retrieval/telemetry/__init__.py
decisions:
  - "RootScanner referenced via TYPE_CHECKING to avoid circular imports"
  - "scanner=None is valid for testing — poll() returns 0.0 with no scanner"
  - "_estimate_significance() uses workspace_confidence as proxy for change magnitude"
  - "Backoff triggers after 2 consecutive idle polls (significance < threshold*0.3)"
metrics:
  duration: "6m 20s"
  completed_date: "2026-03-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 1
---

# Phase 03 Plan 03: RootMonitor Adaptive Polling Summary

**One-liner:** `RootMonitor` with adaptive polling (5s->10s->20s->30s) and cumulative significance threshold (>=0.7 triggers re-score), with 10s debounce and `monitor.py` exported from telemetry package.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| RED | Failing tests for RootMonitor | d76c41a | tests/test_telemetry_monitor.py |
| 1 | Create telemetry/monitor.py | d07c402 | src/multimcp/retrieval/telemetry/monitor.py |
| 2 | Export RootMonitor from __init__.py | 6cc490e | src/multimcp/retrieval/telemetry/__init__.py |

## What Was Built

### `src/multimcp/retrieval/telemetry/monitor.py`

`RootMonitor` class implementing TELEM-05:

- **Adaptive polling:** `_POLL_SCHEDULE = [5.0, 10.0, 20.0, 30.0]` seconds. Starts at index 0 (5s). After 2 consecutive idle polls (significance < 0.21), advances to next interval. Caps at 30s.
- **Significance accumulation:** `record_change(significance)` adds to `_cumulative_significance`. Values are always non-negative (clamped via `max(0.0, significance)`).
- **Threshold check:** `check_for_changes()` returns `True` when `_cumulative_significance >= 0.7` AND time since last trigger >= `min_debounce_s` (default 10s).
- **Acknowledge:** `acknowledge()` resets significance to 0.0, records trigger time, and restores fast (5s) polling.
- **Reset:** `reset()` full state clear — all counters, timers, and schedule index.
- **`poll()`:** Calls scanner if set, returns significance, accumulates via `record_change()`, applies backoff logic.
- **`should_poll()`:** Returns True when `monotonic() - _last_poll_time >= poll_interval`.

### Updated `src/multimcp/retrieval/telemetry/__init__.py`

Added `from .monitor import RootMonitor` and `"RootMonitor"` to `__all__`. Enables `from src.multimcp.retrieval.telemetry import RootMonitor`.

## Verification

All plan verification checks pass:

```
from src.multimcp.retrieval.telemetry.monitor import RootMonitor  # OK
from src.multimcp.retrieval.telemetry import RootMonitor  # OK
RootMonitor().poll_interval == 5.0  # True
m = RootMonitor(min_debounce_s=0.0); m.record_change(0.8); m.check_for_changes() == True  # True
m.acknowledge(); m.check_for_changes() == False  # True (in debounce)
```

Test results: **23/23 telemetry monitor tests pass**, **65/65 total telemetry tests pass**, **70/70 Phase 2 retrieval pipeline tests pass**.

## Deviations from Plan

None — plan executed exactly as written. The TDD flow (RED -> GREEN -> commit) was followed precisely. The implementation matches the code shown in the plan's `<action>` block with no modifications needed.

## Known Stubs

None. `RootMonitor` is fully functional. `_estimate_significance()` uses `workspace_confidence` directly as change magnitude proxy — this is intentional (documented in code comment), not a stub.

## Self-Check: PASSED

Files created:
- `src/multimcp/retrieval/telemetry/monitor.py` - FOUND
- `tests/test_telemetry_monitor.py` - FOUND

Files modified:
- `src/multimcp/retrieval/telemetry/__init__.py` - FOUND (contains RootMonitor)

Commits:
- `d76c41a` - FOUND (RED tests)
- `d07c402` - FOUND (GREEN implementation)
- `6cc490e` - FOUND (__init__.py export)
