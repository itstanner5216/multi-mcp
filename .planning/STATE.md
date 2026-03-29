# Project State

## Current Status

- **Milestone:** Phase 2 — BMXF Routing
- **Current Phase:** 2 (Safe Lexical MVP)
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

Last session: 2026-03-28
Stopped at: Phase 1 complete. All 42 new tests pass (test_catalog_snapshot, test_bmx_retriever). Ready to start Phase 2.

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
