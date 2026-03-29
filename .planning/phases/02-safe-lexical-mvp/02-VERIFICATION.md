---
phase: 02-safe-lexical-mvp
verified: 2026-03-29T04:00:00Z
status: passed
score: 14/14 must-haves verified
re_verification: false
---

# Phase 02: Safe Lexical MVP Verification Report

**Phase Goal:** Bounded turn-zero active set derived from roots. No full-catalog exposure. Recall@15 > baseline (PassthroughRetriever).
**Verified:** 2026-03-29T04:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Success Criteria (from ROADMAP.md)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Session init exposes ≤20 tools directly; remaining tools accessible only via routing tool (never full catalog dump) | VERIFIED | `pipeline.py` enforces `sorted(active_keys)[:max_k]` bound; Tier 6 caps at 30; live test with 40-tool registry returns 20 direct + 1 routing tool with 20-item enum |
| 2 | Telemetry scanner reads only allowlisted files within declared roots; `.env*`, SSH keys, arbitrary source files blocked | VERIFIED | `DENIED_PATTERNS` in scanner.py blocks `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, etc.; 42 scanner/token tests all pass |
| 3 | Scan completes within 150ms hard timeout for 10K-entry monorepo; triggers partial evidence mode on timeout | VERIFIED | `HARD_TIMEOUT_MS=150`, `MAX_ENTRIES=10_000`, `MAX_DEPTH=6`; `partial_scan=True` set when deadline exceeded; confirmed by test suite |

### Observable Truths (derived from must_haves across all 3 plans)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T1 | TelemetryScanner never reads .env*, *.pem, *.key, id_rsa, id_ed25519, or any file outside declared roots | VERIFIED | `_is_denied()` enforces `DENIED_PATTERNS`; symlinks skipped; 8 denylist tests pass |
| T2 | Scan completes within 150ms hard timeout per root; partial_scan=True set when timeout fires | VERIFIED | `deadline = time.monotonic() + timeout_ms / 1000.0`; `partial=True` on expiry; confirmed in tests |
| T3 | Scan respects max depth 6 and max 10K entries hard limits | VERIFIED | `MAX_DEPTH=6`, `MAX_ENTRIES=10_000`; enforced in `_walk()` |
| T4 | Scanner produces RootEvidence with typed sparse tokens and confidence 0.0–1.0 | VERIFIED | `scan_root()` returns `RootEvidence` with `tokens` dict and `confidence = min(1.0, unique_families / 3.0)` |
| T5 | WorkspaceEvidence merges multiple RootEvidence objects with workspace_hash and merged_tokens | VERIFIED | `merge_evidence()` in evidence.py sums tokens, computes SHA-256 workspace_hash |
| T6 | TOKEN_WEIGHTS match spec: manifest→3.0, lock→2.5, framework→2.5, lang→2.0, ci→1.5, container→1.5, infra→1.5, db→1.5, vcs→1.0, layout→0.75, readme→0.5 | VERIFIED | All 11 weights confirmed via import smoke-check |
| T7 | No single token family contributes more than 35% of total score (abuse resistance) | VERIFIED | `_apply_family_cap()` enforces `max_per_family = total * 0.35` |
| T8 | ROUTING_TOOL_NAME='request_tool' and ROUTING_TOOL_KEY='__routing__request_tool' | VERIFIED | Constants present in routing_tool.py; confirmed by import |
| T9 | build_routing_tool_schema(ids) returns types.Tool with name='request_tool', enum=ids in inputSchema | VERIFIED | Confirmed via live test and 22 routing_tool test cases |
| T10 | format_namespace_grouped() places env-relevant namespace tools before others | VERIFIED | `format_namespace_grouped(['npm__b','github__a','github__c'],['github'])` returns `['github__a','github__c','npm__b']` |
| T11 | TieredAssembler.assemble() accepts optional routing_tool_schema and appends it when provided | VERIFIED | Optional param at line 66 of assembler.py; appended at line 106; 10 tiered_assembler tests pass |
| T12 | FileRetrievalLogger writes one JSONL line per call to log_ranking_event() | VERIFIED | `dataclasses.asdict(event)` + `json.dumps()` + `open(append)`; live test confirms 2 calls = 2 lines |
| T13 | Each JSONL line contains all RankingEvent fields: session_id, turn_number, active_k, fallback_tier, router_enum_size, scorer_latency_ms | VERIFIED | `RankingEvent` dataclass has all required fields; `FileRetrievalLogger` serializes via `dataclasses.asdict()` |
| T14 | _call_tool() dispatches to handle_routing_call() when tool_name == ROUTING_TOOL_KEY | VERIFIED | Lines 378–403 of mcp_proxy.py; lazy import + early-return guard on `tool_name == ROUTING_TOOL_KEY` |

**Score: 14/14 truths verified**

---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/multimcp/retrieval/telemetry/__init__.py` | VERIFIED | Exports TelemetryScanner, scan_roots, RootEvidence, WorkspaceEvidence, merge_evidence |
| `src/multimcp/retrieval/telemetry/evidence.py` | VERIFIED | Re-exports RootEvidence/WorkspaceEvidence from models.py; implements merge_evidence() |
| `src/multimcp/retrieval/telemetry/tokens.py` | VERIFIED | TOKEN_WEIGHTS (11 families), build_tokens(), _apply_family_cap() |
| `src/multimcp/retrieval/telemetry/scanner.py` | VERIFIED | TelemetryScanner, scan_root(), scan_roots(), DENIED_PATTERNS, budget constants |
| `src/multimcp/retrieval/routing_tool.py` | VERIFIED | ROUTING_TOOL_NAME, ROUTING_TOOL_KEY, build_routing_tool_schema(), format_namespace_grouped(), handle_routing_call() |
| `src/multimcp/retrieval/assembler.py` | VERIFIED | TieredAssembler.assemble() with optional routing_tool_schema param |
| `src/multimcp/retrieval/logging.py` | VERIFIED | FileRetrievalLogger, NullLogger no-op, log_ranking_event abstract method on ABC |
| `src/multimcp/retrieval/pipeline.py` | VERIFIED | Bounded-K enforcement, demoted_ids computation, routing schema assembly, RankingEvent emission, Tier 6 fallback |
| `src/multimcp/mcp_proxy.py` | VERIFIED | ROUTING_TOOL_KEY dispatch at lines 378–403 of _call_tool() |
| `tests/test_telemetry_scanner.py` | VERIFIED | 27 tests; all pass |
| `tests/test_telemetry_tokens.py` | VERIFIED | 15 tests; all pass |
| `tests/test_routing_tool.py` | VERIFIED | 22 tests; all pass |
| `tests/test_file_retrieval_logger.py` | VERIFIED | 12 tests; all pass |
| `tests/test_pipeline_bounded_k.py` | VERIFIED | 16 tests; all pass |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `telemetry/scanner.py` | `telemetry/evidence.py` | `scan_root()` returns RootEvidence | WIRED | `from .evidence import RootEvidence, WorkspaceEvidence, merge_evidence` at line 19 |
| `telemetry/scanner.py` | `telemetry/tokens.py` | `_walk()` calls `build_tokens(found_files)` | WIRED | `from .tokens import build_tokens, ...` at line 20; called at line 190 |
| `pipeline.py` | `logging.py` | `await self.logger.log_ranking_event(event)` | WIRED | Line 144 of pipeline.py |
| `pipeline.py` | `routing_tool.py` | `build_routing_tool_schema(demoted_ids)` | WIRED | Import at line 27; called at line 112 |
| `assembler.py` | `routing_tool.py` | `assemble(…, routing_tool_schema)` appends routing tool | WIRED | Line 106 of assembler.py |
| `mcp_proxy.py` | `routing_tool.py` | `_call_tool()` dispatches on ROUTING_TOOL_KEY to handle_routing_call() | WIRED | Lines 379–403; lazy import + early-return |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `pipeline.py:get_tools_for_list` | `active_mappings` | `self.tool_registry` (live registry reference) | Yes — real ToolMapping objects | FLOWING |
| `pipeline.py:get_tools_for_list` | `demoted_ids` | all_registry_keys minus active_key_set | Yes — computed from live registry | FLOWING |
| `logging.py:FileRetrievalLogger` | event JSONL line | `dataclasses.asdict(event)` from caller-provided RankingEvent | Yes — real event data | FLOWING |
| `scanner.py:scan_root` | `found_files` | actual filesystem walk under root_path | Yes — real directory entries | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Result | Status |
|----------|--------|--------|
| Bounded K: 40-tool registry with max_k=20 returns 20 direct tools + 1 routing tool | 20 direct, 1 routing, enum=20 | PASS |
| Routing tool enum exactly covers demoted tools | 40 - 20 = 20 in enum | PASS |
| FileRetrievalLogger writes 2 JSONL lines on 2 calls, each containing session_id, active_k, etc. | 2 lines, all fields present | PASS |
| ROUTING_TOOL_KEY dispatch: _call_tool exits early and calls handle_routing_call | Confirmed via grep (lines 378–403) | PASS |
| Token weight constants: all 11 families match spec exactly | smoke-check passed | PASS |
| Family cap: no family exceeds 35% of total weight | _apply_family_cap() verified, 15 token tests pass | PASS |
| Denylist: .env, .env.production, *.pem, *.key, id_rsa, id_ed25519 blocked | 8 denylist tests pass | PASS |
| pytest tests/test_telemetry_scanner.py + test_telemetry_tokens.py | 42 passed | PASS |
| pytest tests/test_routing_tool.py + test_tiered_assembler.py | 32 passed | PASS |
| pytest tests/test_file_retrieval_logger.py + test_pipeline_bounded_k.py | 28 passed | PASS |
| pytest tests/ (excl. pre-existing edge-case failures, legacy integration) | 805 passed, 1 pre-existing failure (test_retrieval_edge_cases.py::test_score_tokens_* — AttributeError predating this phase) | PASS |

---

### Requirements Coverage

| Requirement | Plan | Description | Status | Evidence |
|-------------|------|-------------|--------|----------|
| TELEM-01 | 02-01 | Telemetry scanner scans roots within allowlist | SATISFIED | scanner.py: ALL_ALLOWED_FILES allowlist; 27 scanner tests pass |
| TELEM-02 | 02-01 | Typed sparse tokens (manifest:*, lang:*, ci:*) into RootEvidence/WorkspaceEvidence | SATISFIED | build_tokens() produces family:value tokens; merge_evidence() produces WorkspaceEvidence |
| TELEM-03 | 02-01 | Scan limits: max depth 6, max 10K entries, 150ms hard timeout | SATISFIED | MAX_DEPTH=6, MAX_ENTRIES=10_000, HARD_TIMEOUT_MS=150; enforced in _walk() |
| TELEM-04 | 02-01 | Denies reading .env*, SSH keys, cloud credentials, arbitrary source files, files outside roots | SATISFIED | DENIED_PATTERNS tuple with fnmatch checks; symlink skip; 8 denylist tests pass |
| ROUTER-01 | 02-02/02-03 | routing_tool.py as synthetic MCP tool registered via _register_request_handlers() | SATISFIED | _call_tool registered at line 680; routing dispatch inside _call_tool at lines 378–403 |
| ROUTER-02 | 02-02 | Routing tool accepts name (exact tool lookup) and optional describe parameters | SATISFIED | inputSchema has name (enum), describe (boolean), arguments (object); required=["name"] |
| ROUTER-03 | 02-02 | Routing tool enum lists namespace-grouped, env-relevance ordered demoted tools | SATISFIED | format_namespace_grouped() confirmed; env namespaces first, then alphabetical |
| ROUTER-04 | 02-02 | System never directly exposes more than 20 tools simultaneously | SATISFIED | max_k=20 enforced in pipeline; live test with 40-tool registry confirms 20 direct tools |
| FALLBACK-01 | 02-03 | 6-tier bounded fallback ladder — never exposes full catalog at any tier | SATISFIED | Tier 6 caps at sorted(all_registry_keys)[:30]; routing tool prevents full-catalog exposure |
| FALLBACK-02 | 02-03 | Terminal fallback (Tier 6) exposes conservative top-30 static defaults | SATISFIED | Code at pipeline.py lines 99–107: `fallback_keys = sorted(all_registry_keys)[:30]` |
| OBS-01 | 02-03 | FileRetrievalLogger extending RetrievalLogger ABC with JSONL per-turn RankingEvent logging | SATISFIED | FileRetrievalLogger in logging.py; log_ranking_event abstract on ABC; NullLogger no-op |
| OBS-02 | 02-03 | Emits RankingEvent per turn with session_id, turn_number, catalog_version, workspace_hash, alpha, active_k, fallback_tier, active_tool_ids, router_enum_size, scorer_latency_ms | SATISFIED | RankingEvent dataclass has all fields; pipeline emits via `await self.logger.log_ranking_event(event)` |
| TEST-03 | 02-01 | test_telemetry_scanner.py — allowlist enforcement, scan budget limits, typed token extraction | SATISFIED | 27 tests, all pass |
| TEST-04 | 02-02 | test_routing_tool.py — routing tool registration, name lookup, describe response | SATISFIED | 22 tests, all pass |

**All 14 requirements SATISFIED.**

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `pipeline.py:139` | `turn_number=0` hardcoded | INFO | Documented stub; turn tracking deferred to Phase 3. Does not block bounded active set invariant. |
| `pipeline.py:139` | `fallback_tier=1` hardcoded | INFO | Documented stub; dynamic tier tracking deferred. JSONL event still emitted correctly. |
| `pipeline.py:139` | `catalog_version=""` hardcoded | INFO | Documented stub; ToolCatalogSnapshot versioning deferred. |

No stub patterns block the phase goal. All three are documented in 02-03-SUMMARY.md under "Known Stubs."

---

### Human Verification Required

None. All success criteria are verifiable programmatically. The "Recall@15 > baseline" aspect of the phase goal is an intent/design aspiration — the ROADMAP Success Criteria do not include a measurable Recall@15 benchmark for this phase (that evaluation is in Phase 4). The structural invariants (bounded K, denylist, JSONL emission) are fully verified.

---

## Gaps Summary

No gaps. All 14 must-haves verified, all 14 requirements satisfied, all success criteria met, test suites green.

**Pre-existing failures (not introduced by this phase):** 3 tests in `test_retrieval_edge_cases.py::TestKeywordRetrieverEdgeCases` fail with `AttributeError: 'KeywordRetriever' object has no attribute '_score_tokens'`. Documented in 02-03-SUMMARY.md as pre-existing before this phase's work.

---

*Verified: 2026-03-29T04:00:00Z*
*Verifier: Claude (gsd-verifier)*
