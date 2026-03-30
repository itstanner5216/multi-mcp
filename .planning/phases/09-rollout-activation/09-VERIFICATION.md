---
phase: 09-rollout-activation
verified: 2026-03-30T00:00:00Z
status: partial
score: 6/6 supersession corrections applied
re_verification: false
---

# Phase 9: Rollout Activation — Gap Closure Verification Report

**Phase Goal:** Close V-01 through V-06 audit findings by wiring real runtime behavior and replacing structural grep-checks with behavioral end-to-end tests.
**Verified:** 2026-03-30
**Status:** partial (worktree scope: replay metrics, rescore tracking, verification doc corrections)

---

## Supersession Corrections (V-01 through V-06)

This phase corrects six overstated claims found in prior verification documents by the implementation audit (`docs/implementation-audit-final.md`). Each correction is listed below with:
- The original false/overstated claim
- The root cause
- The fix applied
- The replacement test

---

### V-01 — pipeline.py → fusion.py: import-only, not runtime

| Field | Value |
|-------|-------|
| **Original claim** | `03-VERIFICATION.md` Key Links: "pipeline.py → fusion.py: WIRED" |
| **Root cause** | `weighted_rrf` was imported (import-only check) but never invoked inside `get_tools_for_list()` — the RRF blend never ran at runtime. |
| **Fix** | Phase 7 (07-01): `weighted_rrf` and `compute_alpha` wired into the scoring path inside `get_tools_for_list()`. |
| **Replacement test** | `tests/test_e2e_rrf_called.py::test_rrf_called_on_turn_gt_0` |

---

### V-02 — ROUTING_TOOL_KEY dispatch confirmed via grep, not behavior

| Field | Value |
|-------|-------|
| **Original claim** | `02-VERIFICATION.md` T14: "_call_tool() dispatches to handle_routing_call() when tool_name == ROUTING_TOOL_KEY — confirmed via grep (lines 378–403)" |
| **Root cause** | Grep confirmed code structure only. Actual dispatch was broken due to `ROUTING_TOOL_NAME` vs `ROUTING_TOOL_KEY` name mismatch; `handle_routing_call()` was never reached. |
| **Fix** | Phase 7 (07-01): ROUTING_TOOL_NAME dispatch fixed, name mismatch resolved. |
| **Replacement test** | `tests/test_e2e_routing_dispatch.py::test_request_tool_callable` |

---

### V-03 — "Full Phase 3 adaptive loop is live" — turn counter wired, RRF not called

| Field | Value |
|-------|-------|
| **Original claim** | `03-VERIFICATION.md` Summary: "full Phase 3 adaptive loop is live" |
| **Root cause** | Turn counter incremented in `on_tool_called()` and `promote()` wired, but `weighted_rrf` / `compute_alpha` were never called in the hot path. The scoring still used linear passthrough ranking. |
| **Fix** | Phase 7 (07-01): `weighted_rrf` + `compute_alpha` wired into `get_tools_for_list()` blend. |
| **Replacement test** | `tests/test_e2e_rrf_called.py::test_rrf_called_on_turn_gt_0` |

---

### V-04 — "≤20 tools verified via live test" — test/production config mismatch

| Field | Value |
|-------|-------|
| **Original claim** | `02-VERIFICATION.md` Success Criterion #1: "live test with 40-tool registry returns 20 direct + 1 routing tool" |
| **Root cause** | Test used `enabled=True` explicitly. Production code (`multi_mcp.py`) hardcoded `enabled=False`, so the pipeline always short-circuited and returned all tools. The production path never exercised bounded behavior. |
| **Fix** | Phase 9 (09-01): `RetrievalSettings` exposes `enabled` field in YAML; `multi_mcp.py` reads `enabled` from config instead of hardcoding `False`; runtime semantics tested for each rollout stage. |
| **Replacement test** | `tests/test_rollout_runtime_modes.py::test_config_driven_pipeline_init`, `test_ga_mode` |

---

### V-05 — Session isolation test used distinct IDs, proxy hardcoded "default"

| Field | Value |
|-------|-------|
| **Original claim** | `03-VERIFICATION.md` SESSION-04: "session isolation — not shared across sessions — SATISFIED" |
| **Root cause** | Unit test injected distinct session IDs directly into `SessionStateManager`. The proxy layer (`MCPProxyServer`) hardcoded `session_id="default"` for all sessions, so all real traffic shared one state. |
| **Fix** | Phase 8 (08-01): Transport-derived real session IDs passed through the proxy, eliminating the hardcoded `"default"`. |
| **Replacement test** | `tests/test_e2e_session_isolation.py::test_real_proxy_sessions_distinct_ids` |

---

### V-06 — ALERT_RESCORE_RATE constant defined but never used in check()

| Field | Value |
|-------|-------|
| **Original claim** | `04-VERIFICATION.md` Truth #12: "AlertChecker with correct thresholds — VERIFIED (ALERT_DESCRIBE_RATE=0.10, ALERT_TIER56_RATE=0.05, ALERT_P95_MS=75.0)" |
| **Root cause** | `ALERT_RESCORE_RATE = 0.2` was defined as a module constant but never referenced in `AlertChecker.__init__()` or `check()`. The rescore-rate alert was dead code. |
| **Fix** | Phase 9 (09-01): `rescore_threshold: float = ALERT_RESCORE_RATE` parameter added to `AlertChecker.__init__()`; `HIGH_RESCORE_RATE` check wired into `check()` using `snapshot.rescore_rate_10m`. `RollingMetrics.record_rescore()` added as producer; `pipeline.rebuild_catalog()` calls it. |
| **Replacement test** | `tests/test_alert_rescore_rate.py::test_rescore_alert_sustained_10m`, `tests/test_e2e_alert_rescore.py::test_rebuild_triggers_record_rescore` |

---

## Worktree Scope (Phase 9 Safe Parallel Package)

This verification doc covers work done in `claude/beautiful-brattain` branch. The following changes were implemented:

### Files Modified

| File | Change | Requirement |
|------|--------|-------------|
| `src/multimcp/retrieval/replay.py` | Added `recall_at_15`, `canary_recall`, `control_recall`, `canary_describe_rate`, `control_describe_rate` to `ReplayMetrics`; added Recall@15 gate (Gate 3) and describe-rate gate (Gate 4) to `check_cutover_gates()`; shadow group excluded; N≥20 guard | closes gap for recall and describe-rate gate correctness |
| `src/multimcp/retrieval/metrics.py` | Added `record_rescore()` to `RollingMetrics`; added `rescore_rate_30m` and `rescore_rate_10m` to `MetricSnapshot`; added `rescore_threshold` param and `HIGH_RESCORE_RATE` alert to `AlertChecker` | V-06 fix |
| `src/multimcp/retrieval/pipeline.py` | Added `rolling_metrics: RollingMetrics \| None = None` constructor param; `rebuild_catalog()` calls `self._rolling_metrics.record_rescore()` when set | V-06 producer wiring |
| `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` | Added supersession notice + V-02 and V-04 inline annotations | V-02, V-04 |
| `.planning/phases/03-turn-by-turn-adaptive/03-VERIFICATION.md` | Added supersession notice + V-01, V-03, V-05 inline annotations | V-01, V-03, V-05 |
| `.planning/phases/04-rollout-hardening/04-VERIFICATION.md` | Added supersession notice + V-06 inline annotation | V-06 |

### Tests Written (this worktree)

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/test_replay_cutover_gates.py` | `test_recall_includes_router_proxies`, `test_recall_blocks_insufficient_data`, `test_describe_rate_relative_drop`, `test_describe_rate_blocks_insufficient` | Recall gate, describe-rate gate, shadow exclusion, N≥20 guard |
| `tests/test_alert_rescore_rate.py` | `test_rescore_alert_sustained_10m`, `test_rescore_alert_not_30m_only` | V-06 rescore alert correctness |
| `tests/test_e2e_alert_rescore.py` | `test_rebuild_triggers_record_rescore` | Producer→consumer path for rescore rate |
| `tests/test_phase9_verification_supersession.py` | `test_supersession_notices_exist`, `test_09_verification_exists` | Verification doc correctness |

### Out-of-Scope (handled in main branch or other workstreams)

The following Phase 9 changes were NOT implemented in this worktree (hardcoded Phase 8 dependency boundary):
- `src/multimcp/yaml_config.py` — `RetrievalSettings` YAML field expansion (F-06)
- `src/multimcp/multi_mcp.py` — YAML-driven pipeline init (F-06, F-09)
- `tests/test_rollout_runtime_modes.py` — runtime semantics tests
- `tests/test_e2e_routing_dispatch.py`, `test_e2e_rrf_called.py`, `test_e2e_production_config.py`, `test_e2e_session_isolation.py`

---

## Score

6/6 supersession corrections applied (V-01 through V-06 all annotated in source verification docs and documented here with replacement tests).

---

_Verified: 2026-03-30_
_Verifier: Claude (gsd-executor, beautiful-brattain worktree)_
