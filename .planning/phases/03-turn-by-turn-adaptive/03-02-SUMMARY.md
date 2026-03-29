---
phase: 03-turn-by-turn-adaptive
plan: 02
subsystem: retrieval/session
tags: [session-management, hysteresis, promote-demote, tdd, phase3]
dependency_graph:
  requires:
    - src/multimcp/retrieval/models.py (RetrievalConfig)
    - src/multimcp/retrieval/session.py (SessionStateManager)
  provides:
    - SessionStateManager.promote() — adds tools at turn boundary, returns newly promoted keys
    - SessionStateManager.demote() — removes tools with hysteresis constraints
  affects:
    - tests/test_session_promote_demote.py
tech_stack:
  added: []
  patterns:
    - Hysteresis-bounded demotion (max_per_turn cap + used_this_turn protection)
    - Safe-default returns (empty list for unknown sessions)
key_files:
  created:
    - tests/test_session_promote_demote.py
  modified:
    - src/multimcp/retrieval/session.py
decisions:
  - promote() returns only newly added keys, skipping already-active tools (mirrors add_tools() semantics)
  - demote() filters candidates in list order then slices to max_per_turn (deterministic, preserves caller's priority ordering)
  - Both methods return [] for unknown sessions — safe default, no exception raised
metrics:
  duration: ~5 minutes
  completed: 2026-03-29
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 03 Plan 02: Promote/Demote Hysteresis on SessionStateManager Summary

**One-liner:** Added `promote()` and `demote()` methods to `SessionStateManager` with hysteresis safety constraints (used_this_turn protection, max_per_turn=3 cap), plus 16-test suite verifying SESSION-01–04 and TEST-05.

## What Was Built

### Task 1: Add promote() and demote() to SessionStateManager (SESSION-01–04)

Added two new methods to `src/multimcp/retrieval/session.py` after `add_tools()` and before `cleanup_session()`:

**`promote(session_id, tool_keys) -> list[str]`**
- Adds tools to the active set at turn boundary
- Returns only newly promoted keys (skips already-active tools)
- Returns `[]` for unknown sessions (safe default)

**`demote(session_id, tool_keys, used_this_turn, max_per_turn=3) -> list[str]`**
- Removes tools from active set with hysteresis safety constraints (SESSION-03)
- Never demotes tools present in `used_this_turn`
- Demotes at most `max_per_turn` tools per call
- Returns `[]` for unknown sessions (safe default)

All existing methods (`get_or_create_session`, `get_active_tools`, `add_tools`, `cleanup_session`) remain unchanged.

**Commit:** `041d9c1`

### Task 2: Create test_session_promote_demote.py (TEST-05)

Created `tests/test_session_promote_demote.py` with 16 tests across 4 test classes:

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestPromote` | 5 | New tool addition, duplicate skip, unknown session, empty list, isolation |
| `TestDemote` | 6 | Removal, used_this_turn protection, max_per_turn cap, unknown session, nonexistent tool, empty list |
| `TestSessionIsolation` | 4 | SESSION-04: active sets never shared across sessions |
| `TestAddToolsBackwardCompat` | 1 | Backward compatibility of existing add_tools() |

All 16 new tests pass. All 16 existing tests in `test_retrieval_session.py` continue to pass (32 total, 0 failures).

**Commit:** `d3227a5`

## Verification Results

```
src/multimcp/retrieval/session.py:51: def promote
src/multimcp/retrieval/session.py:65: def demote
pytest tests/test_session_promote_demote.py tests/test_retrieval_session.py: 32 passed
```

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| demote() slices safe_to_demote[:max_per_turn] in input order | Deterministic; preserves caller's priority ordering; simple |
| promote()/demote() return [] for unknown sessions | Consistent with add_tools() behavior; no exception raised |
| Tests use pytest fixtures (not setup_method) | Matches plan spec; cleaner than class-level setup |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all methods are fully implemented and tested.

## Self-Check: PASSED

- `src/multimcp/retrieval/session.py` exists and contains `def promote` and `def demote`
- `tests/test_session_promote_demote.py` exists with 16 test cases
- Commit `041d9c1` (feat: add promote/demote) exists
- Commit `d3227a5` (test: add test_session_promote_demote.py) exists
- 32/32 tests pass, 0 failures
