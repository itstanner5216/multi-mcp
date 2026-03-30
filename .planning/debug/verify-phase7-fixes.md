# Phase 7 Deviation Fixes — Verification Report

**Verified:** 2025-07-14  
**Status:** ✅ ALL PASS  
**Test suite:** 1032 passed, 0 failed  

---

## Check-by-check Results

### Check 1 — Issue 1: Runtime activation (`multi_mcp.py`)

**Claim:** `RetrievalConfig(enabled=True, shadow_mode=False)`, `rebuild_index()` called at startup, `TelemetryScanner` instantiated.

**Evidence** (`src/multimcp/multi_mcp.py`, lines 505–525):
```python
retrieval_config = RetrievalConfig(
    enabled=True,
    shadow_mode=False,
    rollout_stage="ga",
)
bmxf_retriever = BMXFRetriever(config=retrieval_config)
...
if self.proxy.tool_to_server:
    bmxf_retriever.rebuild_index(self.proxy.tool_to_server)
...
telemetry_scanner = TelemetryScanner()
```

**Result:** ✅ PASS — `enabled=True`, `shadow_mode=False`, `rebuild_index()` called, `TelemetryScanner` instantiated.

---

### Check 2 — Issue 2: Router describe targets recorded (`mcp_proxy.py`)

**Claim:** After a `describe=True` routing call, `retrieval_pipeline.record_router_describe(session_id, name)` is called.

**Evidence** (`src/multimcp/mcp_proxy.py`, lines 456–460):
```python
# Issue 2 fix: record describe targets to pipeline session state so
# get_session_router_describes() has real data for conversation context.
if describe and name and self.retrieval_pipeline is not None:
    session_id = self._get_session_id()
    self.retrieval_pipeline.record_router_describe(session_id, name)
```

**Result:** ✅ PASS — `record_router_describe` called with real `session_id` and `name` after `describe=True` routing.

---

### Check 3a — Issue 3a: `RankingEvent.timestamp` field (`retrieval/models.py`)

**Claim:** `RankingEvent` has `timestamp: float` field with `default_factory=time.time`.

**Evidence** (`src/multimcp/retrieval/models.py`, line 162):
```python
timestamp: float = field(default_factory=time.time)  # Unix epoch at emission
```
`time` is imported at line 5; `field` from `dataclasses` at line 6.

**Result:** ✅ PASS — field present with correct type and default factory.

---

### Check 3b — Issue 3b: Tier 5 parser reads `event.get("timestamp")` (`pipeline.py`)

**Claim:** Tier 5 parser uses `event.get("timestamp")`, not multi-fallback heuristics.

**Evidence** (`src/multimcp/retrieval/pipeline.py`, lines 347–350):
```python
# Use the timestamp field added to RankingEvent (Issue 3 fix).
# Legacy events without timestamp fall back to treating all entries
...
event_ts = event.get("timestamp")
```

**Result:** ✅ PASS — parser reads `event.get("timestamp")` directly.

---

### Check 3c — Issue 3c: `direct_tool_calls` and `router_proxies` populated at emission (`pipeline.py`)

**Claim:** At `RankingEvent` emission, `direct_tool_calls` populated from `_session_tool_history` and `router_proxies` from `_session_router_describes`.

**Evidence** (`src/multimcp/retrieval/pipeline.py`, lines 664–683):
```python
session_direct_calls = list(self._session_tool_history.get(session_id, []))
session_router_proxies = list(self._session_router_describes.get(session_id, []))
...
direct_tool_calls=session_direct_calls,
router_proxies=session_router_proxies,
```

**Result:** ✅ PASS — both fields populated from live session state at emission time.

---

### Check 4 — Issue 4: `RankingEvent.alpha` uses real `fusion_alpha` (`pipeline.py`)

**Claim:** `alpha=fusion_alpha`, not `alpha=ws_confidence`.

**Evidence** (`src/multimcp/retrieval/pipeline.py`, lines 669–677):
```python
# Emit RankingEvent (OBS-02) — use real fusion_alpha (Issue 4 fix)
...
workspace_confidence=ws_confidence,
...
alpha=fusion_alpha,  # actual fusion alpha from _compute_alpha (0.0 if Tier 1 not used)
```
`fusion_alpha` is computed by `_compute_alpha()` at line 577; `ws_confidence` is a separate variable tracking raw workspace confidence.

**Result:** ✅ PASS — `alpha=fusion_alpha` (not `ws_confidence`).

---

### Check 5 — Issue 5: K-slot semantics — `direct_k = dynamic_k` (`pipeline.py`)

**Claim:** `direct_k = dynamic_k` with no `- 1` subtraction.

**Evidence** (`src/multimcp/retrieval/pipeline.py`, lines 509–510):
```python
# direct_k always equals dynamic_k so retrieval results fill all K slots.
direct_k = dynamic_k
```

**Result:** ✅ PASS — `direct_k = dynamic_k`, no slot stolen for routing tool.

---

### Check 6 — Issue 6: Real session IDs in `on_tool_called` (`mcp_proxy.py`)

**Claim:** `on_tool_called` uses `self._get_session_id()`, not the string literal `"default"`.

**Evidence** (`src/multimcp/mcp_proxy.py`, lines 536–540):
```python
# hardcoded "default" so Phase 7 session-grounded signals work.
_session_id = self._get_session_id()
disclosed = await self.retrieval_pipeline.on_tool_called(
    _session_id, tool_name, arguments
)
```

**Result:** ✅ PASS — `_get_session_id()` called; `"default"` string literal is gone from the call site.

---

### Check 7 — Issue 7: Turn-boundary design (`pipeline.py`)

**Claim:** `on_tool_called()` does NOT call `session_manager.promote()`. `get_tools_for_list()` IS where promotion happens.

**Evidence — `on_tool_called` (`pipeline.py`, lines 734–753):**
```python
Does NOT increment turns or promote — those happen at turn boundaries
(i.e., when get_tools_for_list() is called for the next request).
...
Issue 7 fix: separate "record tool used" from "promote/advance turn".
...
# Do NOT call session_manager.promote() here — promotion happens at the
# turn boundary in get_tools_for_list() so all tools from a single request
# are promoted together, not one-by-one mid-request.
```
No `session_manager.promote()` call appears inside `on_tool_called`.

**Evidence — `get_tools_for_list` (`pipeline.py`, lines 483–493):**
```python
# Turn boundary: advance the turn counter and promote tools recorded since
# the last tools/list call. This separates "record tool used" (on_tool_called)
# from "promote/advance turn" (here, at the true turn boundary).
# Issue 7 fix: promote happens once per turn, not per tool call.
...
if recent_tools and hasattr(self.session_manager, "promote"):
    self.session_manager.promote(session_id, recent_tools)
```

**Result:** ✅ PASS — separation of concerns correctly enforced.

---

### Check 10 — Test suite

**Claim:** 1032 passed, 0 failed.

**Command:** `uv run pytest tests/ -q --ignore=tests/e2e_test.py --ignore=tests/k8s_test.py`

**Output:**
```
1032 passed in 19.19s
```

**Result:** ✅ PASS — 1032 passed, 0 failed, 0 errors.

---

## Summary

| # | Issue | File(s) | Status |
|---|-------|---------|--------|
| 1 | Runtime activation | `multi_mcp.py` | ✅ PASS |
| 2 | Router describe targets recorded | `mcp_proxy.py` | ✅ PASS |
| 3a | `RankingEvent.timestamp` field | `retrieval/models.py` | ✅ PASS |
| 3b | Tier 5 parser reads `event.get("timestamp")` | `retrieval/pipeline.py` | ✅ PASS |
| 3c | `direct_tool_calls` / `router_proxies` at emission | `retrieval/pipeline.py` | ✅ PASS |
| 4 | `RankingEvent.alpha = fusion_alpha` | `retrieval/pipeline.py` | ✅ PASS |
| 5 | `direct_k = dynamic_k` (no slot stolen) | `retrieval/pipeline.py` | ✅ PASS |
| 6 | Real session IDs in `on_tool_called` | `mcp_proxy.py` | ✅ PASS |
| 7 | Turn-boundary: promote in `get_tools_for_list` only | `retrieval/pipeline.py` | ✅ PASS |
| — | Test suite: 1032 passed, 0 failed | all | ✅ PASS |

**Overall Verdict: ✅ ALL 7 DEVIATION FIXES CORRECTLY IMPLEMENTED**

All source code matches the intended behavior described in the debug agent checkpoint. Test suite confirms no regressions.
