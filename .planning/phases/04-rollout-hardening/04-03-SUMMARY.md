---
phase: 04-rollout-hardening
plan: 03
subsystem: retrieval
tags: [canary, rollout, pipeline, logging, bmxf, a/b-testing]

# Dependency graph
requires:
  - phase: 04-01
    provides: get_session_group, rollout_stage/canary_percentage in RetrievalConfig, RankingEvent.group field

provides:
  - Canary routing in pipeline.get_tools_for_list() — shadow/canary/ga stage dispatch
  - RankingEvent.group set per-session via get_session_group()
  - log_alert() in RetrievalLogger ABC, NullLogger, FileRetrievalLogger
  - tests/test_canary_pipeline.py — 10 tests covering all rollout stages

affects:
  - 04-04 (alert monitoring will call log_alert)
  - 05-post-ga-learning (downstream uses rollout_stage=ga as default)
  - 06-verification-compliance (shadow/canary/ga routing is core contract)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - rollout_stage dispatch: shadow=passthrough, canary=hash-based, ga=all-filtered
    - is_filtered flag gates bounded active set vs passthrough in get_tools_for_list
    - RankingEvent.group labeled before emission for offline A/B analysis
    - log_alert() JSONL record: type=alert, alert_name, message, details, timestamp

key-files:
  created:
    - tests/test_canary_pipeline.py
  modified:
    - src/multimcp/retrieval/pipeline.py
    - src/multimcp/retrieval/logging.py
    - tests/test_pipeline_bounded_k.py
    - tests/test_pipeline_phase3.py
    - tests/test_pipeline_wiring.py
    - tests/test_retrieval_e2e.py
    - tests/test_retrieval_integration.py
    - tests/test_retrieval_pipeline.py

key-decisions:
  - "shadow mode (default) returns all tools — existing tests updated to rollout_stage=ga to test filtering"
  - "is_filtered computed once per call: ga=always, canary+group=canary, shadow/control=false"
  - "FileRetrievalLogger.log_alert uses lazy import time as _time to avoid module-level name conflict"

patterns-established:
  - "Rollout stage dispatch: check is_filtered before branching to filtered vs passthrough path"
  - "Existing tests that verify bounded-K/filtering must use rollout_stage=ga explicitly"

requirements-completed: []

# Metrics
duration: 8min
completed: 2026-03-29
---

# Phase 4 Plan 03: Canary Pipeline Integration Summary

**Canary routing wired into pipeline.get_tools_for_list() — shadow/canary/ga stage dispatch with per-session group labeling on RankingEvent, plus log_alert() added to the logging ABC**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-29T18:19:30Z
- **Completed:** 2026-03-29T18:27:30Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments
- pipeline.get_tools_for_list() now dispatches based on rollout_stage: shadow/control=passthrough, canary=hash-based, ga=all-filtered
- RankingEvent.group set to session's assigned group ("canary"|"control") before emission
- log_alert() abstract method added to RetrievalLogger ABC with no-op NullLogger and JSONL-appending FileRetrievalLogger implementations
- 10 new tests in test_canary_pipeline.py covering all 3 rollout stages, kill switch, and group labeling
- 958 total tests passing (948 pre-existing + 10 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire canary routing into pipeline.get_tools_for_list()** - `7d4215e` (feat)
2. **Task 2: Extend logging.py with log_alert() method** - `41f64e0` (feat)
3. **Task 3: Create tests/test_canary_pipeline.py** - `3b8b97b` (test)

## Files Created/Modified
- `src/multimcp/retrieval/pipeline.py` - Added rollout import + is_filtered dispatch + group=group in RankingEvent
- `src/multimcp/retrieval/logging.py` - Added log_alert() to ABC, NullLogger, FileRetrievalLogger
- `tests/test_canary_pipeline.py` - New: 10 tests for canary routing (shadow/canary/ga/kill-switch/groups)
- `tests/test_pipeline_bounded_k.py` - Updated make_pipeline to use rollout_stage="ga"
- `tests/test_pipeline_phase3.py` - Updated TestDynamicK tests to use rollout_stage="ga"
- `tests/test_pipeline_wiring.py` - Updated filtering tests to use rollout_stage="ga"
- `tests/test_retrieval_e2e.py` - Updated e2e filtering tests to use rollout_stage="ga"
- `tests/test_retrieval_integration.py` - Updated integration test to use rollout_stage="ga"
- `tests/test_retrieval_pipeline.py` - Updated anchor/session tests to use rollout_stage="ga"

## Decisions Made
- shadow mode (default) returns all tools — pre-existing tests that expected filtering were updated to use `rollout_stage="ga"` to preserve their intent
- `is_filtered` is computed once per call from `rollout_stage` + `group`, keeping the branch logic simple
- `FileRetrievalLogger.log_alert` uses lazy `import time as _time` to avoid naming collision with the module-level time usage

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated 16 pre-existing tests from shadow (broken) to GA (correct) for filtering tests**
- **Found during:** Task 1 (Wire canary routing)
- **Issue:** 16 existing tests used `RetrievalConfig(enabled=True)` expecting filtered results, but the new shadow-mode-is-passthrough behavior broke them. These tests were correct in intent (testing bounded-K filtering) but lacked explicit `rollout_stage`.
- **Fix:** Added `rollout_stage="ga"` to `RetrievalConfig` in each affected test's helper factory or direct config instantiation.
- **Files modified:** tests/test_pipeline_bounded_k.py, tests/test_pipeline_phase3.py, tests/test_pipeline_wiring.py, tests/test_retrieval_e2e.py, tests/test_retrieval_integration.py, tests/test_retrieval_pipeline.py
- **Verification:** 948 tests passing (0 failures) after fix
- **Committed in:** 7d4215e (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - behavior compatibility fix)
**Impact on plan:** Required to preserve all existing test intent under the new rollout_stage semantics. No scope creep.

## Issues Encountered
- None beyond the test compatibility fix documented above.

## Next Phase Readiness
- Pipeline canary routing is fully functional: set `rollout_stage="canary"` and `canary_percentage=10.0` to route 10% of sessions through BMXF filtering
- `log_alert()` is ready for 04-04 alert monitoring to use
- Shadow mode (default) behavior is backward compatible — no operator action needed to preserve existing behavior

---
*Phase: 04-rollout-hardening*
*Completed: 2026-03-29*
