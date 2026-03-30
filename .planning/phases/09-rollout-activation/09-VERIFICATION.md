# Phase 09 Verification — Gap Closure for V-01 through V-06

This document is the authoritative verification record for findings V-01 through V-06 identified in
`docs/implementation-audit-final.md`. Each entry states the original overstated claim, the corrected
status (what was wrong and which phase fixed it), the replacement end-to-end test, and the runtime
behavior that is now verified.

---

## V-01 — weighted_rrf() import-only verification corrected

**Original overstated claim:** `03-VERIFICATION.md` Key Links: "pipeline.py → fusion.py: WIRED"

**Corrected status:** The import succeeded, but `weighted_rrf()` was never called at runtime. Phase 7 (07-01) wires `weighted_rrf()` into `get_tools_for_list()` for every turn > 0, completing the adaptive loop.

**Replacement test:** `tests/test_e2e_rrf_called.py::test_rrf_called_on_turn_gt_0`

**Runtime behavior verified:** Pipeline calls `weighted_rrf(env_ranked, conv_ranked, alpha)` at runtime when turn > 0 and conversation context is available.

---

## V-02 — Routing dispatch grep-only verification corrected

**Original overstated claim:** `02-VERIFICATION.md` T14: "dispatch confirmed via grep"

**Corrected status:** Grep confirmed code structure, not runtime behavior. Dispatch was broken due to name mismatch: dispatch checked `ROUTING_TOOL_KEY` (`"__routing__request_tool"`) but the model calls `ROUTING_TOOL_NAME` (`"request_tool"`). Phase 7 (07-01) fixes dispatch to check `tool_name == ROUTING_TOOL_NAME`.

**Replacement test:** `tests/test_e2e_routing_dispatch.py::test_request_tool_callable`

**Runtime behavior verified:** Calling `request_tool` (the model-visible name) reaches `handle_routing_call()`.

---

## V-03 — "Full adaptive loop is live" corrected

**Original overstated claim:** `03-VERIFICATION.md` phase objective: "Full Phase 3 adaptive loop is live"

**Corrected status:** Turn counter and `promote()` were wired, but `weighted_rrf()` and `compute_alpha()` were never invoked. The adaptive loop was structurally incomplete. Phase 7 (07-01) wires the full RRF + alpha computation into every turn > 0.

**Replacement test:** `tests/test_e2e_rrf_called.py::test_rrf_called_on_turn_gt_0`

**Runtime behavior verified:** Turn 0 uses env-only BMXF; turn 1+ uses `weighted_rrf(env_ranked, conv_ranked, alpha)` with decaying alpha per `compute_alpha()`.

---

## V-04 — ≤20 tools production behavior corrected

**Original overstated claim:** `02-VERIFICATION.md` T1: "≤20 tools verified via live test"

**Corrected status:** The test used `enabled=True` but production hardcoded `enabled=False`. The test exercised a code path that production never reached. Phase 9 (09-01) removes the hardcoded `enabled=False`; `multi_mcp.py` now reads `enabled` from YAML config.

**Replacement test:** `tests/test_e2e_production_config.py::test_config_driven_pipeline_init`

**Runtime behavior verified:** Production pipeline init reads `enabled` from YAML; when `enabled=True` and `rollout_stage="ga"`, bounded set enforcement is active and at most 20 tools are exposed.

---

## V-05 — Session isolation corrected

**Original overstated claim:** `03-VERIFICATION.md` SESSION-04: "Session isolation satisfied"

**Corrected status:** The unit test used distinct session IDs as parameters, but the proxy hardcoded `session_id="default"` for every real session. All real sessions shared the same state with no isolation. Phase 8 (08-01) wires `_get_session_id()` using `id(_server_session)` per connection.

**Replacement test:** `tests/test_e2e_session_isolation.py::test_real_proxy_sessions_distinct_ids`

**Runtime behavior verified:** Two concurrent proxy sessions receive distinct session IDs; `SessionRoutingState` is separate per session with no state leakage.

---

## V-06 — AlertChecker rescore rate corrected

**Original overstated claim:** `04-VERIFICATION.md` truth #12: "AlertChecker with correct thresholds"

**Corrected status:** `ALERT_RESCORE_RATE = 0.2` was defined but never passed to `AlertChecker.__init__()` and never checked in `AlertChecker.check()`. The threshold constant existed but was inert. Phase 9 (09-01) adds `rescore_rate_10m` to `MetricSnapshot`, wires `record_rescore()` in `_do_rebuild()`, and adds `rescore_rate_10m > 0.2` check in `AlertChecker.check()`.

**Replacement tests:**
- `tests/test_alert_rescore_rate.py` — unit-level rescore rate threshold and metric snapshot validation
- `tests/test_e2e_alert_rescore.py::test_rebuild_triggers_record_rescore` — end-to-end rebuild→alert path
- `tests/test_replay_cutover_gates.py` — replay cutover gate checks with rescore rate guard

**Runtime behavior verified:** Multiple catalog rebuilds produce `rescore_rate_10m > 0.2` which triggers the `HIGH_RESCORE_RATE` alert from `AlertChecker.check()`.
