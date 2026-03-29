---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 04
status: Executing Phase 04
stopped_at: "Completed 04-02-PLAN.md: Offline replay evaluator for BMXF rollout gate-keeping"
last_updated: "2026-03-29T18:14:14.834Z"
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 17
  completed_plans: 8
---

# Project State

## Current Status

- **Milestone:** Phase 3 — Turn-by-Turn Adaptive
- **Current Phase:** 04
- **Phase Status:** ✅ Complete — verified 2026-03-29 (922 tests passing, 20/20 must-haves)
- **Last Updated:** 2026-03-29

## Active Phase

**Phase 3: Turn-by-Turn Adaptive**

Goal: Per-session turn tracking, dynamic K (FUSION-03), RRF fusion blend in pipeline, RootMonitor adaptive polling.

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundations | ✅ Complete |
| 2 | Safe Lexical MVP | ✅ Complete |
| 3 | Turn-by-Turn Adaptive | ✅ Complete (4/4 plans) |
| 4 | Rollout Hardening | 📋 Planned (4 plans) |
| 5 | Post-GA Learning | 📋 Planned (3 plans) |
| 6 | Verification & Compliance | 📋 Planned (1 plan) |

## Session Continuity

Last session: 2026-03-29T18:14:14.831Z
Stopped at: Completed 04-02-PLAN.md: Offline replay evaluator for BMXF rollout gate-keeping

## Context Notes

- Plan source: `docs/PHASE2-SYNTHESIZED-PLAN.md`
- Existing retrieval module at `src/multimcp/retrieval/` — 46+ tests must stay green
- BMX source to copy: `/home/tanner/MCPServer/src/meta_mcp/rag/retrieval/bmx.py`
- Tool namespace format: `server_name__tool_name` (double underscore via `_make_key()`)
- `MCPProxyServer.retrieval_pipeline` is currently TYPE_CHECKING-only import, `Optional[RetrievalPipeline] = None`
- New retrievers must implement `rebuild_index(registry: dict[str, ToolMapping])` pattern

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-28 | BMX over BM25/TF-IDF as primary scorer | +1.15 nDCG@10 on BEIR; self-tuning params; pure Python; no external deps |
| 2026-03-28 | BMXF field weighting (5 sub-indexes) | 5-10% accuracy on name/namespace — strongest retrieval signal in tool corpus |
| 2026-03-28 | Shadow mode mandatory before enabling | Safe migration; existing behavior preserved until metrics confirm improvement |
| 2026-03-28 | Conservative K=15-20 | Lean context window; routing tool as safety net for missed tools |
| 2026-03-29 | Re-export RootEvidence/WorkspaceEvidence from models.py | canonical source stays in models.py; evidence.py is a re-export shim |
| 2026-03-29 | Family cap applied against original total (not post-cap) | simpler, avoids iterative convergence; 35% of original total per family |
| 2026-03-29 | Confidence = min(1.0, unique_families/3) | 3 distinct signal families as heuristic for rich workspace context |
| 2026-03-29 | Lazy import ROUTING_TOOL_KEY in _call_tool() | Avoids circular import between mcp_proxy and retrieval subpackage |
| 2026-03-29 | RankingEvent.turn_number=0 for Phase 2 | Turn tracking deferred to Phase 3 |
| 2026-03-29 | Tier 6 fallback capped at 30 (not 20) | Wider visibility in zero-state sessions without full-registry exposure |
| 2026-03-29 | demote() slices safe_to_demote[:max_per_turn] in input order | Deterministic; preserves caller's priority ordering |
| 2026-03-29 | promote()/demote() return [] for unknown sessions | Consistent with add_tools() safe-default pattern; no exception raised |
| 2026-03-29 | Polyglot detection via config.max_k>17 heuristic | Conservative; full WorkspaceEvidence threading deferred; lets operators opt-in via config |
| 2026-03-29 | on_tool_called promotes tool_name if in registry (promote-on-call) | Immediate disclosure of called tool; simpler than RRF blend at call time |
