---
phase: 03-turn-by-turn-adaptive
plan: "04"
subsystem: retrieval/pipeline
tags: [pipeline, turn-tracking, dynamic-k, fusion, phase3, tdd]
dependency_graph:
  requires:
    - src/multimcp/retrieval/fusion.py (03-01: weighted_rrf, compute_alpha)
    - src/multimcp/retrieval/session.py (03-02: promote, demote)
    - src/multimcp/retrieval/models.py (SessionRoutingState, RankingEvent, RetrievalConfig.max_k)
    - src/multimcp/retrieval/logging.py (NullLogger.log_ranking_event)
    - src/multimcp/retrieval/assembler.py (TieredAssembler.assemble with routing_tool_schema)
  provides:
    - src/multimcp/retrieval/pipeline.py — turn tracking, dynamic K, fusion wiring
  affects:
    - All callers of RetrievalPipeline.on_tool_called() (mcp_proxy._call_tool)
tech_stack:
  added: []
  patterns:
    - Per-session turn counter dict (_session_turns)
    - Dynamic K with floor=15 and polyglot bonus (+3 when max_k>17)
    - Optional fusion import with _HAS_FUSION guard
    - Promote-on-call: on_tool_called triggers session_manager.promote()
key_files:
  created:
    - tests/test_pipeline_phase3.py
  modified:
    - src/multimcp/retrieval/pipeline.py
    - src/multimcp/retrieval/fusion.py (brought from 03-01 branch)
    - src/multimcp/retrieval/session.py (brought from 03-02 branch with promote/demote)
    - src/multimcp/retrieval/models.py (brought from 03-03 branch with all Phase 2/3 models)
    - src/multimcp/retrieval/logging.py (brought from 03-03 branch with log_ranking_event)
    - src/multimcp/retrieval/assembler.py (brought from 03-03 branch with routing_tool_schema)
    - tests/test_rrf_fusion.py (brought from 03-01 branch)
    - tests/test_session_promote_demote.py (brought from 03-02 branch)
decisions:
  - Brought Phase 2/3 supporting files from parallel worktrees — each prior plan ran on its own branch
  - Polyglot detection via config.max_k>17 heuristic (conservative; full WorkspaceEvidence threading deferred)
  - on_tool_called promotes tool_name if it exists in tool_registry (promote-on-call pattern)
  - Turn counter increments even when pipeline is enabled but tool is not in registry
metrics:
  duration_minutes: 16
  completed_date: "2026-03-29"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 8
---

# Phase 03 Plan 04: Pipeline Phase 3 Wiring Summary

**One-liner:** Wired turn tracking (_session_turns dict), dynamic K (base 15, +3 polyglot, cap 20), and RRF fusion import into RetrievalPipeline, replacing the turn_number=0 and always-False on_tool_called stubs.

## What Was Built

### Updated `src/multimcp/retrieval/pipeline.py`

**1. Fusion import (try/except guard):**

```python
try:
    from .fusion import weighted_rrf, compute_alpha
    _HAS_FUSION = True
except ImportError:
    _HAS_FUSION = False
    weighted_rrf = None
    compute_alpha = None
```

**2. Per-session turn tracking dict:**

```python
self._session_turns: dict[str, int] = {}  # session_id -> current turn number
```

**3. on_tool_called() — no longer a stub:**

- Increments `_session_turns[session_id]` on every call
- Short-circuits with `return False` when pipeline is disabled (no tracking)
- Calls `session_manager.promote(session_id, [tool_name])` when tool is in registry
- Returns `True` when `promote()` returns newly-added keys

**4. RankingEvent.turn_number fix:**

Replaced `turn_number=0` placeholder with `turn_number=self._session_turns.get(session_id, 0)`.

**5. Dynamic K (FUSION-03):**

```python
base_k = max(15, self.config.max_k)
polyglot_bonus = 3 if self.config.max_k > 17 else 0
max_k = min(20, base_k + polyglot_bonus)
```

### New test file `tests/test_pipeline_phase3.py`

17 tests across 5 test classes (TDD):

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestTurnTracking` | 5 | _session_turns init, increment, multi-call, isolation, disabled |
| `TestOnToolCalledPromote` | 4 | not-in-registry, already-active, new tool true, turn increments always |
| `TestRankingEventTurnNumber` | 2 | turn_number=0 initially, turn_number=2 after two calls |
| `TestDynamicK` | 4 | max_k=20 stays 20, max_k=10 bumped to 15, max_k=18 gets bonus, max_k=5 uses floor |
| `TestFusionImport` | 2 | _HAS_FUSION attribute exists, _HAS_FUSION is True |

### Supporting files brought from parallel worktrees

This worktree (branch `worktree-agent-a321d4ef`) branched from main before the Phase 2/3 work. Previous plans (03-01, 03-02, 03-03) ran on separate parallel worktrees. To execute this plan, the following files were copied from their respective source branches:

| File | Source Branch | Content |
|------|--------------|---------|
| `src/multimcp/retrieval/fusion.py` | worktree-agent-a7b82a4a (03-01) | weighted_rrf, compute_alpha |
| `src/multimcp/retrieval/session.py` | worktree-agent-af45195d (03-02) | promote(), demote() |
| `src/multimcp/retrieval/models.py` | worktree-agent-ad76f8af (03-03) | Full Phase 2/3 dataclasses |
| `src/multimcp/retrieval/logging.py` | worktree-agent-ad76f8af (03-03) | log_ranking_event in NullLogger |
| `src/multimcp/retrieval/assembler.py` | worktree-agent-ad76f8af (03-03) | routing_tool_schema param |
| `tests/test_rrf_fusion.py` | worktree-agent-a7b82a4a (03-01) | 20 fusion tests |
| `tests/test_session_promote_demote.py` | worktree-agent-af45195d (03-02) | 16 promote/demote tests |

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| RED | Failing tests for Phase 3 pipeline | 493c0f8 | tests/test_pipeline_phase3.py |
| GREEN | Wire Phase 3 into pipeline | f684892 | pipeline.py + 8 supporting files |

## Verification

```
grep -n "_HAS_FUSION|weighted_rrf|_session_turns|turn_number" pipeline.py  # 7 matches
grep "turn_number=0" pipeline.py  # no output (placeholder removed)
python -c "from src.multimcp.retrieval.pipeline import RetrievalPipeline; print('OK')"  # OK
pytest tests/ (excluding pre-existing failure + e2e)  # 724 passed
```

## Deviations from Plan

### Auto-fixed Issues (Rule 3 - Blocking)

**1. [Rule 3 - Blocking] Brought supporting Phase 2/3 files from parallel worktrees**
- **Found during:** Setup — worktree had pre-Phase-2 code state
- **Issue:** This worktree branched from main before Phase 2/3 work; lacked fusion.py, updated session.py, models.py, logging.py, assembler.py
- **Fix:** Copied 7 files from their respective source branches using `git show <branch>:<path>`
- **Files modified:** fusion.py, session.py, models.py, logging.py, assembler.py, test_rrf_fusion.py, test_session_promote_demote.py
- **Commit:** f684892

**2. [Rule 3 - Blocking] logging.py missing log_ranking_event method**
- **Found during:** GREEN test run — NullLogger had no log_ranking_event
- **Issue:** Pipeline calls `await self.logger.log_ranking_event(event)` but local logging.py predates this addition
- **Fix:** Brought updated logging.py from 03-03 branch (includes abstract method + NullLogger no-op + FileRetrievalLogger)
- **Commit:** f684892

**3. [Rule 3 - Blocking] assembler.py missing routing_tool_schema parameter**
- **Found during:** Full test run — TypeError: assemble() got unexpected keyword argument
- **Issue:** Pipeline calls assemble(..., routing_tool_schema=...) but local assembler.py predates this param
- **Fix:** Brought updated assembler.py from 03-03 branch
- **Commit:** f684892

### Pre-existing failure (out of scope)

`tests/test_retrieval_edge_cases.py::TestKeywordRetrieverEdgeCases::test_score_tokens_empty_doc` — AttributeError on `_score_tokens`. Pre-existing failure noted in 03-01 SUMMARY. Not introduced by this plan. Excluded from regression check.

## Known Stubs

- `_HAS_FUSION` flag is `True` (fusion.py is present) but `weighted_rrf`/`compute_alpha` are not yet called in `get_tools_for_list()` — the imports are wired and ready, but the actual RRF blend call (replacing `score=1.0` with fused scores) is deferred. This is intentional per the plan scope: the plan wires the import and on_tool_called promotion; full conv-signal scoring is the next integration step.
- `compute_alpha()` is imported but not yet invoked in the pipeline — the alpha decay is available but not connected to the ranking call. This is noted in the plan as the conservative approach.

## Self-Check: PASSED

Files verified:
- `src/multimcp/retrieval/pipeline.py` — FOUND, contains `_session_turns`, `_HAS_FUSION`, `turn_number=self._session_turns.get`
- `src/multimcp/retrieval/fusion.py` — FOUND
- `tests/test_pipeline_phase3.py` — FOUND

Commits:
- `493c0f8` — FOUND (RED tests)
- `f684892` — FOUND (GREEN implementation)

Verification:
- `grep "turn_number=0" pipeline.py` — no matches
- `pytest 724 passed` — confirmed
