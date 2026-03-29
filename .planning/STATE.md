---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 3
status: Ready to plan
stopped_at: "Completed 02-03-PLAN.md: FileRetrievalLogger, bounded-K pipeline, routing tool dispatch in mcp_proxy"
last_updated: "2026-03-29T04:22:13.583Z"
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 5
  completed_plans: 3
---

# Project State

## Current Status

- **Milestone:** Phase 2 — BMXF Routing
- **Current Phase:** 3
- **Phase Status:** Not started
- **Last Updated:** 2026-03-28

## Active Phase

**Phase 2: Safe Lexical MVP**

Goal: Bounded turn-zero active set derived from roots. No full-catalog exposure. Recall@15 > baseline (PassthroughRetriever).

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundations | ✅ Complete |
| 2 | Safe Lexical MVP | 🔲 Not started |
| 3 | Turn-by-Turn Adaptive | 🔲 Not started |
| 4 | Rollout Hardening | 🔲 Not started |
| 5 | Post-GA Learning | 🔲 Not started |

## Session Continuity

Last session: 2026-03-29T03:41:30.000Z
Stopped at: Completed 02-03-PLAN.md: FileRetrievalLogger, bounded-K pipeline, routing tool dispatch in mcp_proxy

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
