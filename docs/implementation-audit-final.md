# Implementation Audit — Phases 1–4 (Synthesized Final)

**Source of Truth:** `docs/PHASE2-SYNTHESIZED-PLAN.md`
**Audit Scope:** Code in `src/multimcp/retrieval/`, `src/multimcp/mcp_proxy.py`, `src/multimcp/multi_mcp.py` vs source plan requirements and phase plan docs under `.planning/phases/01-*` through `.planning/phases/04-*`
**Method:** Literal code review only. No inferences from documentation outside the source of truth.
**Synthesized from:** `implementation-audit.md` (prior audit) and `implementation-audit2.md` (code-grounded audit)
**Date:** 2026-03-29

---

## Material Deviation Report

---

### F-01 — `request_tool` advertised in tools/list but is not callable end-to-end

**Severity:** Critical
**Category:** claimed-but-not-wired

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:999-1000` requires `routing_tool.py` to be registered in `_register_request_handlers()` and `docs/PHASE2-SYNTHESIZED-PLAN.md:321-326` requires every bounded path to remain valid via the router. Phase 2 must-have T14: "\_call\_tool() dispatches to handle\_routing\_call() when tool\_name == ROUTING\_TOOL\_KEY."

**What exists instead:**
The routing tool's MCP schema is built by `build_routing_tool_schema()` with `types.Tool(name="request_tool", ...)` — that is the name the model sees in `tools/list` and the name it will call. The proxy dispatch condition is `if _has_routing and tool_name == ROUTING_TOOL_KEY` where `ROUTING_TOOL_KEY = "__routing__request_tool"`. When a model calls `"request_tool"`, the condition `"request_tool" == "__routing__request_tool"` is always `False`. The call falls through to `tool_to_server.get("request_tool")` which returns `None`, and the response is `"Tool 'request_tool' not found!"`. The routing tool is permanently broken as a callable MCP tool.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/routing_tool.py` lines 20–21: `ROUTING_TOOL_NAME = "request_tool"`, `ROUTING_TOOL_KEY = "__routing__request_tool"`
- `src/multimcp/retrieval/routing_tool.py` lines 24–56: `build_routing_tool_schema()` returns `types.Tool(name="request_tool", ...)`
- `src/multimcp/mcp_proxy.py` lines 371–403: dispatch condition uses `ROUTING_TOOL_KEY`
- `.planning/phases/02-safe-lexical-mvp/02-03-PLAN.md` lines 53–58
- `.planning/phases/02-safe-lexical-mvp/02-03-SUMMARY.md` lines 93–95, 174–177
- `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` lines 39–45, 62–63, 98–103, 122–123: T14 behavioral spot-check confirmed via grep, not via end-to-end call with `"request_tool"` as name

**Where the issue exists:** code + verification

---

### F-02 — Session isolation broken: hardcoded `"default"` session ID in all proxy calls

**Severity:** Critical
**Category:** claimed-but-not-wired

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:324-325` makes per-session isolation a core invariant. `docs/PHASE2-SYNTHESIZED-PLAN.md:1009-1014` requires Phase 2 state to be session-scoped. `SessionStateManager` is designed with per-`session_id` scoped state in `_sessions: dict[str, set[str]]`.

**What exists instead:**
`mcp_proxy.py` passes the string literal `"default"` as `session_id` in every call to `retrieval_pipeline.get_tools_for_list()` (line 350) and `retrieval_pipeline.on_tool_called()` (line 477). All MCP clients share one active set, one turn counter, and one rollout cohort. `SessionStateManager` correctly isolates distinct string IDs in unit tests, but the integration path never passes real session IDs. A TODO comment acknowledges this: `# TODO: extract real session_id from MCP request context when available`.

**Exact file paths and line numbers:**
- `src/multimcp/mcp_proxy.py` line 350: `tools = await self.retrieval_pipeline.get_tools_for_list("default")`
- `src/multimcp/mcp_proxy.py` lines 474–481: `await self.retrieval_pipeline.on_tool_called("default", tool_name, arguments)`
- `src/multimcp/retrieval/session.py` lines 15–27, 51–87
- `.planning/phases/03-turn-by-turn-adaptive/03-VERIFICATION.md` lines 113–119, 131–139: SESSION-04 "SATISFIED" verified only that `SessionStateManager` handles distinct IDs in unit tests; never tested that proxy passes distinct IDs
- `.planning/phases/04-rollout-hardening/04-VERIFICATION.md` lines 29–35, 67–72, 107–115

**Where the issue exists:** code + verification

---

### F-03 — BMXF retriever.retrieve() and weighted_rrf/compute_alpha never called; Phase 3 adaptive loop is dead code

**Severity:** Critical
**Category:** claimed-but-not-wired

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:295-307` defines the per-turn execution flow: "Compute blended score via weighted RRF (k=10): `final_rrf(tool) = α/(10+rank_env(t)) + (1-α)/(10+rank_conv(t))`; `α = max(0.15, 0.85·e^(−0.25·turn))`." `docs/PHASE2-SYNTHESIZED-PLAN.md:1004-1014` makes environment-only ranking and turn-by-turn RRF the Phase 2–3 scope. Phase 3 plan 03-04 objective: "After this plan, the full Phase 3 adaptive loop is live. Each tool call increments the turn counter, alpha decays accordingly, and the active set is scored via weighted RRF blending environment + conversation signals."

**What exists instead:**
`pipeline.py` imports `_weighted_rrf` and `_compute_alpha` from `.fusion` via an `_HAS_FUSION` guard (lines 16–19), but neither function is called anywhere in `get_tools_for_list()` or `on_tool_called()`. `BMXFRetriever.retrieve()` is fully implemented (lines 168–230) but is never called by the pipeline — `self.retriever` is stored in `__init__` and used only in `rebuild_catalog()`. The active set is built entirely from `session_manager.get_active_tools(session_id)` (a monotonic key-set) with no scoring whatsoever. The only "dynamic K" logic is `config.max_k > 17` as a config-heuristic proxy for polyglot workspaces, not a scoring-derived signal.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/pipeline.py` lines 15–18: import-only; no call sites in `get_tools_for_list()` body
- `src/multimcp/retrieval/pipeline.py` lines 95–101: dynamic K block; no `self.retriever.retrieve()` call anywhere in file
- `src/multimcp/retrieval/fusion.py` lines 14–88: `weighted_rrf` and `compute_alpha` defined but uncalled
- `src/multimcp/retrieval/bmx_retriever.py` lines 168–230: `retrieve()` implemented but unreachable from pipeline
- `.planning/phases/03-turn-by-turn-adaptive/03-VERIFICATION.md` Key Link "pipeline.py → fusion.py": claims "WIRED" based on `_HAS_FUSION=True` (import), not an actual call
- `.planning/phases/03-turn-by-turn-adaptive/03-04-SUMMARY.md` lines 50–52

**Where the issue exists:** code + verification

---

### F-04 — Telemetry subsystem built but never connected to the pipeline; turn-zero routing falls back to sorted registry order

**Severity:** Critical
**Category:** dropped

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:273-293` defines roots-driven session-init ranking. `docs/PHASE2-SYNTHESIZED-PLAN.md:994-1002` makes environment-only ranking at session init (using roots scan) the Phase 2 exit condition. The session-init execution flow is: `roots/list` → allowlisted scan → `RootEvidence[]` → `WorkspaceEvidence` → BMXF scoring (environment query) → initial active set.

**What exists instead:**
`telemetry/scanner.py`, `telemetry/tokens.py`, `telemetry/evidence.py`, and `telemetry/monitor.py` are fully implemented as isolated modules. No call to `scan_root()`, `scan_roots()`, `TelemetryScanner`, or `RootMonitor` exists in `pipeline.py`, `mcp_proxy.py`, or `multi_mcp.py`. No `WorkspaceEvidence` or `RootEvidence` object is ever created in any production code path. When the pipeline has no active keys for a session, it seeds the active set with `sorted(all_registry_keys)[:self.config.max_k]` — pure alphabetical order with no environmental signal.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/pipeline.py` lines 89–118: session seeding via `sorted(all_registry_keys)[:self.config.max_k]`; no telemetry import
- `src/multimcp/retrieval/pipeline.py` lines 149–151
- `src/multimcp/retrieval/telemetry/scanner.py` lines 88, 206–258: `scan_root()`, `scan_roots()` defined and unused
- `src/multimcp/multi_mcp.py` lines 504–512: zero telemetry imports
- `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` lines 11, 24, 157: T1–T7 verify scanner behavior in isolation; no verification that pipeline calls scanner at session init

**Where the issue exists:** code + verification

---

### F-05 — Six-tier fallback ladder: Tiers 1–5 absent; Tier 6 violates max-20 invariant and omits routing tool

**Severity:** Critical
**Category:** dropped / softened

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:889-920` defines a six-tier ladder:

| Tier | Trigger | Action |
|------|---------|--------|
| 1 | Normal operation | BMXF env + conversation blend |
| 2 | Conv query weak/failed | BMXF env-only |
| 3 | BMXF unavailable/corrupt | TF-IDF env-only (KeywordRetriever) |
| 4 | No usable scorer, project_type_guess confident | Static category defaults |
| 5 | Static type weak, 7-day prior available | Time-decayed frequency prior |
| 6 | Everything above unavailable | Universal 12-tool set + routing tool |

Core invariant (`docs/PHASE2-SYNTHESIZED-PLAN.md:320`): "Max directly exposed = 20. Remaining in routing tool." Core invariant: "Bounded degradation: Every fallback tier returns a bounded, valid active set plus router."

**What exists instead:**
`pipeline.py` has exactly one fallback path labeled "Tier 6" (line 119). It fires when `active_mappings` is empty. No tier evaluation, no `KeywordRetriever` fallback (exists as a class, never instantiated in a fallback path), no static category defaults, no frequency prior. The Tier 6 path at lines 119–127 exposes `sorted(all_registry_keys)[:30]` as direct tools with `demoted_ids = []` — no routing tool is built for this case. This exposes up to 30 direct tools (violating max-20) with no routing tool covering the remainder (a different behavior, not a narrower implementation of the 12+router spec). The `fallback_tier` field in `RankingEvent` is hardcoded to `1` at all times regardless of which path executed. The Phase 2 plan quietly rewrote Tier 6 as "top-30 static defaults" (vs source plan's "12+routing tool") — that rewrite is itself a deviation from the source plan that verification then accepted.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/pipeline.py` lines 103–127: single "Tier 6" path; `fallback_keys = sorted(all_registry_keys)[:30]`; `demoted_ids = []`
- `src/multimcp/retrieval/pipeline.py` line 161: `fallback_tier=1` hardcoded
- `src/multimcp/retrieval/keyword.py`: `KeywordRetriever` exists but never instantiated in any fallback path
- No static category YAML or defaults file anywhere in the project
- `.planning/phases/02-safe-lexical-mvp/02-03-SUMMARY.md` lines 79, 93, 128, 160–166
- `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` lines 24, 126–127, 141–145, 157: FALLBACK-02 "SATISFIED" adopts the "top-30" definition from the phase plan, obscuring the deviation from source plan max-20 invariant
- `docs/PHASE2-SYNTHESIZED-PLAN.md` Core Invariants table: "Max directly exposed = 20"

**Where the issue exists:** code + plan docs + verification

---

### F-06 — Production server hardcodes `enabled=False`; all filtering permanently bypassed

**Severity:** Critical
**Category:** dropped

**Source-plan requirement:**
Phase 2 goal: "Bounded turn-zero active set derived from roots. No full-catalog exposure." Phase 2 success criterion 1: "Session init exposes ≤20 tools directly; remaining tools accessible only via routing tool (never full catalog dump)." `RetrievalConfig.enabled` is the master kill switch; source plan intends it to be enabled once shadow validation passes.

**What exists instead:**
`multi_mcp.py` line 504 hardcodes `RetrievalConfig(enabled=False, shadow_mode=True)`. The `enabled=False` master kill switch causes `pipeline.py:get_tools_for_list()` lines 67–69 to short-circuit: `if not self.config.enabled: return [m.tool for m in self.tool_registry.values()]`. Every active code path — bounded K, routing tool injection, fallback ladder, RRF scoring — is bypassed. The full tool registry is always returned in production. Additionally, `multi_mcp.py` uses `NullLogger()` so no JSONL events are written either. The YAML config path (`yaml_config.py`) exposes none of the Phase 2 retrieval fields (`shadow_mode`, `scorer`, `max_k`, `canary_percentage`, `rollout_stage`), so there is no config-driven path to enable filtering without code changes.

**Exact file paths and line numbers:**
- `src/multimcp/multi_mcp.py` lines 494–512: `RetrievalConfig(enabled=False, shadow_mode=True)`, `NullLogger()`
- `src/multimcp/retrieval/pipeline.py` lines 67–69: `if not self.config.enabled: return all tools`
- `src/multimcp/yaml_config.py` lines 30–35: retrieval fields absent
- `.planning/phases/01-foundations/01-02-PLAN.md` lines 66–72
- `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` T1 behavioral spot-check: "live test with 40-tool registry returns 20 direct" — test used `enabled=True`; production uses `enabled=False`
- `.planning/phases/04-rollout-hardening/04-VERIFICATION.md` lines 11–14, 67–72, 107–115

**Where the issue exists:** code + verification

---

### F-07 — Mid-turn stability invariant violated by immediate promote + `tools/list_changed`

**Severity:** Major
**Category:** substituted

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:303-307` requires promote/demote and router-enum updates at the turn boundary, not during a turn. `docs/PHASE2-SYNTHESIZED-PLAN.md:323` (Core Invariants): "Mid-turn stability: Active set and router enum do not change during a model turn."

**What exists instead:**
`pipeline.py:on_tool_called()` (lines 191–196) immediately calls `session_manager.promote(session_id, [tool_name])` when a tool is invoked. The calling code in `mcp_proxy.py` (lines 474–481) immediately emits `tools/list_changed` if `disclosed=True`. This changes the active set mid-turn — the model receives a `tools/list_changed` notification during its own tool-call sequence, causing the visible tool set to shift before the turn is complete. Additionally, there is no in-turn lock, turn-boundary flag, or "in-turn" guard in `pipeline.py` or `mcp_proxy.py`, so `register_client()`/`unregister_client()` can also call `rebuild_catalog()` at any time.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/pipeline.py` lines 182–205: `on_tool_called()` promotes immediately
- `src/multimcp/mcp_proxy.py` lines 474–481: `tools/list_changed` emitted inline after `on_tool_called()` returns `True`
- `.planning/phases/03-turn-by-turn-adaptive/03-VERIFICATION.md` lines 71–77, 102–103, 131–139: promote behavior verified as a unit; no end-to-end test that list_changed is not emitted mid-turn

**Where the issue exists:** code + verification

---

### F-08 — Snapshot pinning, catalog versioning, and `SessionRoutingState` not implemented

**Severity:** Major
**Category:** claimed-but-not-wired

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:314, 324` requires catalog rebuilds plus turn-boundary snapshot pinning. Core Invariant: "Snapshot pinning: Every turn is pinned to one `ToolCatalogSnapshot.version`." `docs/PHASE2-SYNTHESIZED-PLAN.md:984-985, 1010-1014` makes `ToolCatalogSnapshot` and `SessionRoutingState` part of the implemented phases. `SessionRoutingState` holds `alpha`, `active_k`, `fallback_tier`, `active_tool_ids`, `consecutive_low_rank` — the per-session state needed for hysteresis decisions.

**What exists instead:**
`ToolCatalogSnapshot` and `build_snapshot()` exist and are called by `BMXFRetriever.rebuild_index()`. However, the pipeline never reads the snapshot from the retriever, never pins a turn to a version, and logs `catalog_version=""` on every `RankingEvent` (pipeline.py line 159). `SessionRoutingState` is defined in `models.py` (lines 112–135) with all required fields but is never instantiated or referenced in `pipeline.py`, `mcp_proxy.py`, or `multi_mcp.py`. The pipeline uses only `SessionStateManager._sessions: dict[str, set[str]]` — a flat key-set with no alpha, no consecutive_low_rank, no router_enum tracking. Phase 2 verification acknowledged `catalog_version=""` as a "Known Stub" with "deferred" status; it was never removed.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/catalog.py` lines 41–77: `build_snapshot()` implemented but not consumed by pipeline
- `src/multimcp/retrieval/models.py` lines 73–83: `ToolCatalogSnapshot`; lines 112–132: `SessionRoutingState` (never instantiated in production code)
- `src/multimcp/retrieval/pipeline.py` line 159: `catalog_version=""` hardcoded
- `src/multimcp/retrieval/bmx_retriever.py` line 167: `self._snapshot = snapshot` stored but never read by pipeline
- Grep for `SessionRoutingState` in `src/**/*.py`: only `models.py` line 112 (definition)
- `.planning/phases/02-safe-lexical-mvp/02-03-SUMMARY.md` lines 160–166
- `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` lines 129, 141–145, 151, 157: stub acknowledged

**Where the issue exists:** code + plan docs

---

### F-09 — Shadow/canary rollout infrastructure not wired into server runtime

**Severity:** Major
**Category:** claimed-but-not-wired

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:963-975` defines shadow mode as "compute rankings, log, don't change exposure" and adds staged rollout controls. `docs/PHASE2-SYNTHESIZED-PLAN.md:990, 1017-1020` requires shadow scoring and later rollout hardening as phase exits. The rollout sequence is: Shadow → Canary 10% → Canary 50% → GA 100%.

**What exists instead:**
`MultiMCP` hardcodes `RetrievalConfig(enabled=False, shadow_mode=True)` and `NullLogger()`, so the runtime server short-circuits before any scoring or logging. `enabled=False` (analyzed in F-06) means no ranking occurs at all, making `shadow_mode=True` a no-op. The YAML config path (`yaml_config.py`) does not expose `shadow_mode`, `scorer`, `max_k`, `canary_percentage`, or `rollout_stage`, so rollout cannot be controlled through the shipped config path without code changes. The rollout infrastructure (rollout.py, replay.py, metrics.py) exists in a well-tested but disconnected state.

**Exact file paths and line numbers:**
- `src/multimcp/multi_mcp.py` lines 494–512
- `src/multimcp/retrieval/pipeline.py` lines 73–75: `enabled=False` short-circuit before shadow scoring
- `src/multimcp/yaml_config.py` lines 30–35: retrieval fields absent from YAML schema
- `.planning/phases/01-foundations/01-02-PLAN.md` lines 66–72
- `.planning/phases/04-rollout-hardening/04-VERIFICATION.md` lines 11–14, 67–72, 107–115

**Where the issue exists:** code

---

### F-10 — `demote()` never called from any production code path

**Severity:** Major
**Category:** claimed-but-not-wired

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md` per-turn loop: "Demote: rank below K+3 for 2 consecutive turns, max 3 per turn." Core invariant for session isolation requires preventing stale tools from persisting indefinitely in the active set.

**What exists instead:**
`session.py` implements `demote(session_id, tool_keys, used_this_turn, max_per_turn=3)` correctly (lines 65–84). No call to `demote()` exists in `pipeline.py`, `mcp_proxy.py`, or `multi_mcp.py`. Grep for `\.demote\(` in `src/**/*.py`: only `session.py` line 65 (definition). Only `promote()` is called — from `on_tool_called()` when a tool is directly invoked. The session's active set is therefore monotonically growing and never shrinks. The "demote based on consecutive low rank" criterion also requires `self.retriever.retrieve()` to be called each turn (F-03), which never happens. Phase 3 VERIFICATION verified `demote()` behavior as a unit test but no truth verified that the pipeline calls it.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/session.py` lines 65–84: implementation
- `src/multimcp/retrieval/pipeline.py` lines 191–196: `on_tool_called()` only calls `promote()`; no `demote()` call

**Where the issue exists:** code

---

### F-11 — Rollout cutover gates softened; Recall@15 absent; describe_rate gate semantics inverted

**Severity:** Major
**Category:** softened / dropped

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md:957-961` requires four alerts (describe rate, Tier 5-6, p95, re-score frequency). `docs/PHASE2-SYNTHESIZED-PLAN.md:975-977`: cutover gates are "Recall@15 ≥5% improvement, describe rate ≥20% drop, p95 <50ms, Tier 5-6 <5%." The describe-rate gate is a minimum improvement gate (canary must show ≥20% fewer routing fallbacks than control baseline), proving retrieval improved.

**What exists instead:**
`replay.py:check_cutover_gates()` implements two hard gates (p95 <50ms, tier56 <5%) and one informational check. The describe-rate check has inverted semantics: it flags when rate is too HIGH (>10%) but is always `passed=True` (line 149 hardcodes `passed=True`), and uses no baseline comparison. The ≥20% drop requirement is absent. `Recall@15` computation does not exist anywhere in the codebase. `AlertChecker` in `metrics.py` omits `ALERT_RESCORE_RATE` from all alert-checking logic entirely (the constant exists on line ~107 but is never used in `check()`). Additionally, because `fallback_tier` is hardcoded to 1 (F-05), `tier56_rate` computed in both `replay.py` and `metrics.py` is always 0.0 — the tier56 gate can never be the blocking gate.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/replay.py` lines 128–174: two gates + one informational-only (always passed); no Recall@15
- `src/multimcp/retrieval/replay.py` line 149: `passed=True` hardcoded for describe_rate gate
- `src/multimcp/retrieval/metrics.py` lines 103–149: `ALERT_RESCORE_RATE` defined but not used in `check()`
- `.planning/phases/04-rollout-hardening/04-02-SUMMARY.md` lines 42–53
- `.planning/phases/04-rollout-hardening/04-VERIFICATION.md` lines 27–35, 107–115

**Where the issue exists:** code

---

### F-12 — Promote hysteresis "rank within K-2" criterion never evaluated

**Severity:** Moderate
**Category:** dropped

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md` per-turn section: "Promote: rank within K-2 OR used via router 2/3 last turns." The first criterion requires scoring all tools each turn and checking which fall within the top (K-2) positions.

**What exists instead:**
`pipeline.py:on_tool_called()` (lines 191–196) promotes only via direct invocation signal (`tool_name in self.tool_registry`). The "rank within K-2" path is never evaluated because `self.retriever.retrieve()` is never called (F-03). The "used via router 2/3 last turns" criterion is also missing: `SessionRoutingState.recent_router_proxies` counter exists but `SessionRoutingState` is never instantiated (F-08), so this history is never tracked.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/pipeline.py` lines 191–196: `on_tool_called()` body
- `docs/PHASE2-SYNTHESIZED-PLAN.md` per-turn section: promote criteria

**Where the issue exists:** code

---

### F-13 — `alpha_override=0.5` not set for cold-start environment query mode

**Severity:** Moderate
**Category:** dropped

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md` Section 1 (`bmx_index.py`): "env query mode: alpha_override=0.5 (short tool descriptions → low avgdl)." The env query uses an explicit override because tool descriptions are short (15–200 tokens) and auto-tuned alpha could over-penalize them.

**What exists instead:**
`bmx_retriever.py` line 162: `index = BMXIndex(normalize_scores=True)` — no `alpha_override` set. BMX alpha auto-tunes from corpus avgdl for all query modes. For very short tool descriptions, the auto-tuned alpha can fall below 0.5, over-normalizing short documents. The explicit `alpha_override=0.5` floor for cold-start is absent.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/bmx_retriever.py` line 162: `BMXIndex(normalize_scores=True)` — no alpha_override
- `docs/PHASE2-SYNTHESIZED-PLAN.md` Section 1: "env query mode: alpha_override=0.5"

**Where the issue exists:** code

---

### F-14 — `NAMESPACE_ALIASES` missing production server names; context7 gets zero aliases

**Severity:** Moderate
**Category:** substituted

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md` Section 3 (`bmx_retriever.py`) specifies explicit entries for the three production servers by their exact names:
```
"github":      ["repository", "pull_request", "issue", "git", "code_review", "branch", "commit"],
"brave-search":["web_search", "internet", "lookup", "find", "query"],
"context7":    ["documentation", "library", "docs", "api_reference", "examples"],
```

**What exists instead:**
`bmx_retriever.py` `NAMESPACE_ALIASES` (lines 38–60) uses fragment keys (`"gh"`, `"search"`, `"browser"`, etc.) that are tested as substrings of the server namespace. `"github"` → matches `"gh"` fragment → gets `["github", "repository", "pr", "issue"]` (partial). `"brave-search"` → matches `"search"` fragment → gets `["find", "lookup", "query"]` but loses "web_search" and "internet". `"context7"` → does not contain any registered fragment in the dict → receives zero aliases entirely.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/bmx_retriever.py` lines 38–60: `NAMESPACE_ALIASES` fragment dict
- `docs/PHASE2-SYNTHESIZED-PLAN.md` Section 3: explicit server-name keys

**Where the issue exists:** code

---

### F-15 — `top_k` default changed from 15 to 10

**Severity:** Moderate
**Category:** substituted

**Source-plan requirement:**
`docs/PHASE2-SYNTHESIZED-PLAN.md` Section 2 (`models.py`): `top_k: int = 15` as the default for `RetrievalConfig`.

**What exists instead:**
`src/multimcp/retrieval/models.py` line 40: `top_k: int = 10`. The dynamic K formula in `pipeline.py` (`min(20, max(15, self.config.max_k))`) applies a 15-floor via `max_k=20`, which partially mitigates this in the pipeline. But `BMXFRetriever.retrieve()` and `TieredAssembler` receive `top_k=10` from config when `max_k` is not explicitly set, and operators instantiating `RetrievalConfig()` without overrides get a 10-tool default instead of the spec's 15.

**Exact file paths and line numbers:**
- `src/multimcp/retrieval/models.py` line 40: `top_k: int = 10`
- `docs/PHASE2-SYNTHESIZED-PLAN.md` Section 2: `top_k: int = 15`

**Where the issue exists:** code

---

## Verification Claims That Overstate Reality

The following verification claims are factually accurate as written but create a false impression that behaviors are "wired end-to-end" when they are not.

| ID | File | Claim | Why It Overstates |
|----|------|-------|------------------|
| V-01 | `.planning/phases/03-turn-by-turn-adaptive/03-VERIFICATION.md` Key Links | "`pipeline.py → fusion.py`: imports and calls weighted_rrf, compute_alpha — WIRED" | Only the import is verified (`_HAS_FUSION=True`). Neither function is ever called at runtime (F-03). |
| V-02 | `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` T14 | "\_call\_tool() dispatches to handle\_routing\_call() when tool\_name == ROUTING\_TOOL\_KEY — Confirmed via grep" | Confirmed the code path exists structurally; no behavioral test. Dispatch cannot fire because the model calls `"request_tool"`, not `"__routing__request_tool"` (F-01). |
| V-03 | `.planning/phases/03-turn-by-turn-adaptive/03-04-PLAN.md` objective | "After this plan, the full Phase 3 adaptive loop is live." | Turn counter increments and `promote()` is wired, but `weighted_rrf()` is never called in `get_tools_for_list()` (F-03). The RRF blend does not run. |
| V-04 | `.planning/phases/02-safe-lexical-mvp/02-VERIFICATION.md` T1 | "Session init exposes ≤20 tools directly — VERIFIED — live test with 40-tool registry" | Test used `enabled=True`. Production code uses `enabled=False` (F-06). The bounded behavior is never active in production. |
| V-05 | `.planning/phases/03-turn-by-turn-adaptive/03-VERIFICATION.md` SESSION-04 | "Session state isolation — not shared across sessions — SATISFIED" | `SessionStateManager` correctly handles distinct IDs in unit tests; never tested that `mcp_proxy.py` passes distinct IDs rather than the hardcoded `"default"` (F-02). |
| V-06 | `.planning/phases/04-rollout-hardening/04-VERIFICATION.md` truth #12 | "AlertChecker with correct thresholds — VERIFIED" | Verifies threshold constants exist; never verifies that `ALERT_RESCORE_RATE` is used in `check()` (it isn't) or that tier56 alert can fire in practice (it cannot since `fallback_tier=1` always — F-05). |

---

## Prioritized Deviation List

| Priority | ID | Title | Severity |
|----------|----|-------|----------|
| 1 | F-01 | Routing tool advertised but never callable | Critical |
| 2 | F-06 | `enabled=False` in production; all filtering bypassed | Critical |
| 3 | F-03 | BMXF retrieve() / weighted_rrf / compute_alpha never called | Critical |
| 4 | F-04 | Telemetry subsystem unconnected; turn-zero ranking falls to alphabetical sort | Critical |
| 5 | F-05 | Fallback Tiers 1–5 absent; Tier 6 violates max-20 invariant | Critical |
| 6 | F-02 | Session isolation broken — hardcoded `"default"` session ID | Critical |
| 7 | F-07 | Mid-turn stability violated by immediate promote + tools/list_changed | Major |
| 8 | F-08 | Snapshot pinning and SessionRoutingState not implemented | Major |
| 9 | F-09 | Shadow/canary rollout not wired into server runtime | Major |
| 10 | F-10 | demote() never called; active set grows monotonically | Major |
| 11 | F-11 | Cutover gates softened; Recall@15 absent; describe_rate gate always passes | Major |
| 12 | F-12 | Promote hysteresis "rank within K-2" path absent | Moderate |
| 13 | F-13 | alpha_override=0.5 not set for cold-start env query | Moderate |
| 14 | F-14 | NAMESPACE_ALIASES missing context7 entirely; brave-search partial | Moderate |
| 15 | F-15 | top_k default 10 vs spec 15 | Moderate |

---

## Do-Not-Care Appendix

Items reviewed and intentionally excluded as non-material:

| Item | Reason Excluded |
|------|----------------|
| `replay.py` em-dash vs double-dash in a format string (`BLOCKED -- fix failing gates` vs `BLOCKED — fix failing gates`) | Cosmetic; no behavioral impact. |
| Minor telemetry allowlist mismatches vs source plan | Roots telemetry is not wired into the retrieval path at all (F-04). The parent deviation is the missing integration, not the exact allowlist shape of the disconnected scanner. |
| `FileRetrievalLogger.log_retrieval`, `log_retrieval_miss`, `log_tool_sequence` are no-ops | Source plan's `FileRetrievalLogger` spec also leaves these as no-ops. Consistent with spec. More material deviation is that runtime logging is not wired (F-06/F-09). |
| `RootMonitor` using `workspace_confidence` as a coarse significance proxy | Monitor is not connected to the live pipeline; integration failure is the material issue (F-04). |
| `session.py` retains `add_tools()` alongside `promote()`/`demote()` | `add_tools()` is functionally equivalent to `promote()` for current callers. No behavioral difference. |
| `BMXIndex` alpha auto-tune clamped to [0.5, 1.5] | Clamp range matches source plan spec. Implementation is correct. |
| `RollingMetrics` default window of 1800s | Matches spec "30-min window." |
| `ScoredTool.tier` defaults to `"full"` | Assembler uses it; value is correct for untiered output. |
| `HARD_TIMEOUT_MS=150`, `MAX_ENTRIES=10_000`, `MAX_DEPTH=6` in scanner | All match source plan spec exactly. |
| `rollout.py` uses SHA-256 for bucket assignment | Source plan specifies deterministic hash-based assignment; SHA-256 is acceptable. |
| `bmx_index.py` `build_field_index`/`search_fields` field weights (3.0/2.5/1.5/1.0/0.5) | Match source plan exactly. |
| Test-count drift, summary prose, and phase-doc formatting inconsistencies | Excluded unless they overstate implemented behavior. |
| `NullLogger` used in production wiring | Source plan permits NullLogger as default when no logger configured. Deviation is that shadow logging is never activated (F-06/F-09), not that NullLogger exists. |
| `top_k` effective floor of 15 via dynamic K in pipeline | Partially mitigates F-15 in practice; F-15 retained because the config default is still incorrect and affects `BMXFRetriever.retrieve()` when called directly. |
