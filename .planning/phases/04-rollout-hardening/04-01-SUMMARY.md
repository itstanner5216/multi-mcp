---
phase: 04-rollout-hardening
plan: 01
subsystem: retrieval
tags: [canary, rollout, sha256, session-assignment, bmxf, a-b-testing]

# Dependency graph
requires:
  - phase: 03-turn-by-turn-adaptive
    provides: RetrievalConfig, RankingEvent dataclasses in models.py
provides:
  - RetrievalConfig.canary_percentage and rollout_stage fields
  - RankingEvent.group field for cohort-split metrics
  - rollout.py with is_canary_session() and get_session_group() utilities
  - 16 tests covering determinism, boundaries, distribution, and all rollout stages
affects:
  - 04-02, 04-03, 04-04: pipeline.py will use get_session_group() to route sessions
  - replay evaluator: RankingEvent.group enables cohort-split metric analysis

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SHA-256 hash modulo 100 for deterministic A/B bucket assignment"
    - "Rollout stage enum (shadow/canary/ga) controlling group assignment"
    - "canary_percentage as 0.0-100.0 float (not 0.0-1.0 fraction)"

key-files:
  created:
    - src/multimcp/retrieval/rollout.py
    - tests/test_rollout.py
  modified:
    - src/multimcp/retrieval/models.py
    - src/multimcp/retrieval/__init__.py

key-decisions:
  - "Use SHA-256 instead of MD5 for bucket hashing — identical distribution properties, avoids security scanner false positive (bucket assignment is not cryptographic use)"
  - "canary_percentage range is 0.0-100.0 (not 0.0-1.0) matching plan spec for human-readable config"
  - "rollout.py imported via TYPE_CHECKING for RetrievalConfig to avoid circular import risk"
  - "is_canary_session clamped at <=0.0 and >=100.0 before computing hash — eliminates edge case drift"

patterns-established:
  - "Rollout guard pattern: shadow->control, ga->canary, canary->hash-based"
  - "Deterministic hash split: sha256(session_id)[:8] hex -> int % 100 < canary_percentage"

requirements-completed: []

# Metrics
duration: 4min
completed: 2026-03-29
---

# Phase 4 Plan 01: Canary Rollout Foundation Summary

**SHA-256-based deterministic canary session assignment with rollout stage gating, wired into RetrievalConfig and RankingEvent for cohort-split metrics**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-29T18:10:28Z
- **Completed:** 2026-03-29T18:14:42Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Extended RetrievalConfig with `canary_percentage` (float, default 0.0) and `rollout_stage` (str, default "shadow") — fully backward compatible
- Extended RankingEvent with `group` field (str, default "control") for cohort-split replay evaluation
- Created `rollout.py` with `is_canary_session()` (deterministic SHA-256 bucket assignment) and `get_session_group()` (rollout stage dispatcher)
- 16 tests covering all boundary cases, statistical distribution, determinism, and stage routing

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend RetrievalConfig with canary fields and RankingEvent with group label** - `61b81f3` (feat)
2. **Task 2: Create rollout.py with deterministic canary session assignment** - `f235686` (feat)
3. **Task 3: Create tests/test_rollout.py** - `3cd0aa2` (test)

## Files Created/Modified

- `src/multimcp/retrieval/models.py` - Added canary_percentage, rollout_stage to RetrievalConfig; group to RankingEvent
- `src/multimcp/retrieval/rollout.py` - New: is_canary_session() and get_session_group() utilities
- `src/multimcp/retrieval/__init__.py` - Added rollout exports (is_canary_session, get_session_group)
- `tests/test_rollout.py` - New: 16 tests for canary assignment logic

## Decisions Made

- **SHA-256 over MD5:** The plan specified MD5 for the hash bucket, but the project's security scanner flagged it. Switched to SHA-256 — functionally identical for bucket assignment (uniform distribution, same `digest[:8]` pattern), no collision concerns apply to this non-cryptographic use. Rule 1 auto-fix.
- **canary_percentage clamped before hashing:** `<=0.0` returns False early, `>=100.0` returns True early — handles negative values and values >100 gracefully without error.
- **TYPE_CHECKING guard for RetrievalConfig import in rollout.py:** Avoids any risk of circular imports at runtime; type annotation uses string form.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Replaced MD5 with SHA-256 for hash bucket computation**
- **Found during:** Task 2 (rollout.py creation)
- **Issue:** Project security scanner (PostToolUse hook) blocked the Write with CWE-327 warning on hashlib.md5 usage
- **Fix:** Replaced `hashlib.md5(...)` with `hashlib.sha256(...)` — same algorithm structure, same `digest[:8]` hex-to-int bucket pattern, fully equivalent distribution properties for A/B assignment
- **Files modified:** src/multimcp/retrieval/rollout.py
- **Verification:** All 16 tests pass; is_canary_session determinism and distribution verified
- **Committed in:** f235686 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug/blocker from security scanner)
**Impact on plan:** Functionally equivalent to specified algorithm. No semantic change to canary assignment behavior.

## Issues Encountered

- Security scanner blocked MD5 usage (non-cryptographic use but scanner applies blanket rule) — resolved by switching to SHA-256 with identical structural approach.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `is_canary_session()` and `get_session_group()` ready for pipeline.py integration in 04-02
- `RetrievalConfig.rollout_stage` and `canary_percentage` ready for operator config
- `RankingEvent.group` ready for replay evaluator cohort splitting in 04-03/04-04
- 952 tests passing total (952 = 922 pre-existing + 16 rollout + 14 from __init__ expansion)

---
*Phase: 04-rollout-hardening*
*Completed: 2026-03-29*
