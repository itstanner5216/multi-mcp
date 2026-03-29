---
phase: 03-turn-by-turn-adaptive
plan: "01"
subsystem: retrieval/fusion
tags: [rrf, fusion, alpha-decay, ranking, turn-by-turn]
dependency_graph:
  requires: [src/multimcp/retrieval/models.py]
  provides: [src/multimcp/retrieval/fusion.py, tests/test_rrf_fusion.py]
  affects: [src/multimcp/retrieval/pipeline.py]
tech_stack:
  added: []
  patterns: [weighted-rrf, exponential-alpha-decay, reciprocal-rank-fusion]
key_files:
  created:
    - src/multimcp/retrieval/fusion.py
    - tests/test_rrf_fusion.py
  modified: []
decisions:
  - "Use max_rank penalty (len of list) for tools absent from one ranked list — simpler than RRF_K+1 sentinel and preserves relative order"
  - "alpha floor = 0.15 enforced in both base decay and low-confidence path via max(0.15, ...)"
metrics:
  duration_minutes: 6
  completed_date: "2026-03-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 03 Plan 01: Weighted RRF Fusion and Alpha-Decay Summary

**One-liner:** Weighted RRF fusion (weighted_rrf) and exponential alpha-decay (compute_alpha) implementing turn-by-turn blending of environment and conversation tool rankings.

## What Was Built

`src/multimcp/retrieval/fusion.py` — The mathematical core of Phase 3, providing:

- `weighted_rrf(env_ranked, conv_ranked, alpha)` — fuses two `ScoredTool` rankings via weighted Reciprocal Rank Fusion: `score = alpha/(RRF_K+rank_env) + (1-alpha)/(RRF_K+rank_conv)`. Tools absent from one list receive a max_rank penalty. Returns sorted list by descending fused score.
- `compute_alpha(turn, workspace_confidence, conv_confidence, roots_changed, explicit_tool_mention)` — computes the alpha weight that drives env-to-conversation shift. Base decays from 0.85 (turn 0) to 0.15 floor (turn 10+) via `0.85 * exp(-0.25 * turn)`. Three override conditions: low workspace confidence reduces base by 0.20, explicit tool mention with high conv confidence snaps to 0.15, roots_changed resets to >= 0.80.
- `RRF_K = 10` — exported constant for use by callers.

`tests/test_rrf_fusion.py` — 20 tests covering:
- 9 `TestWeightedRRF` tests: empty inputs, single-list cases, alpha=0/1 extremes, combined score correctness, missing-list tools, RRF formula verification, descending sort guarantee.
- 11 `TestComputeAlpha` tests: turn 0 → 0.85, turn 1 decay, turn 5 midpoint, turns 10/100 at floor, low confidence reduction, explicit mention snap, mention ignored below conv threshold, roots_changed at turn 8 and 10, never-below-0.15 invariant.

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create fusion.py | 45c87a5 | src/multimcp/retrieval/fusion.py |
| 2 | Create test_rrf_fusion.py | 9378fc3 | tests/test_rrf_fusion.py |

## Verification

- `python -c "from src.multimcp.retrieval.fusion import weighted_rrf, compute_alpha"` — exits 0
- `pytest tests/test_rrf_fusion.py` — 20 passed
- Full retrieval test suite (531 tests excluding pre-existing e2e failures) — no regressions introduced

## Deviations from Plan

None — plan executed exactly as written.

**Note on pre-existing test failure:** `tests/test_retrieval_edge_cases.py::TestKeywordRetrieverEdgeCases::test_score_tokens_empty_doc` was already failing before this plan (AttributeError on `_score_tokens`). This is out of scope per deviation rules — logged here for awareness, not fixed.

## Known Stubs

None — fusion.py is fully functional with no placeholder values.

## Self-Check: PASSED
