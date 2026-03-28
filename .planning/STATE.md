# Project State

## Current Status

- **Milestone:** Phase 2 — BMXF Routing
- **Current Phase:** 1 (Foundations)
- **Phase Status:** Not started
- **Last Updated:** 2026-03-28

## Active Phase

**Phase 1: Foundations**

Goal: BMXF scores computed in shadow mode. Existing behavior unchanged. All 46+ existing tests pass.

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundations | 🔲 Not started |
| 2 | Safe Lexical MVP | 🔲 Not started |
| 3 | Turn-by-Turn Adaptive | 🔲 Not started |
| 4 | Rollout Hardening | 🔲 Not started |
| 5 | Post-GA Learning | 🔲 Not started |

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
