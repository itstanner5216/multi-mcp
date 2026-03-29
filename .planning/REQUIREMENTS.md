# Requirements — Multi-MCP Phase 2: BMXF Routing

## v1 Requirements

### Core Scoring Engine (SCORE)

- [ ] **SCORE-01**: System copies BMXIndex from `bmx.py` into `src/multimcp/retrieval/bmx_index.py` and adds BMXF field-weighted wrapper methods (`build_field_index`, `search_fields`)
- [ ] **SCORE-02**: System implements `BMXFRetriever` class implementing `ToolRetriever` ABC with `rebuild_index(registry)` pattern matching `KeywordRetriever`
- [ ] **SCORE-03**: System scores tools across 5 fields with weights: `tool_name(3.0)`, `namespace(2.5)`, `retrieval_aliases(1.5)`, `description(1.0)`, `parameter_names(0.5)`
- [ ] **SCORE-04**: System auto-tunes BMX α from corpus avgdl (clamped 0.5–1.5) and β = 1/log(1+N), eliminating manual k1/b tuning

### Catalog & Data Models (CATALOG)

- [ ] **CATALOG-01**: System defines `ToolDoc` dataclass with fields `tool_key`, `tool_name`, `namespace`, `description`, `parameter_names`, `retrieval_aliases`
- [ ] **CATALOG-02**: System defines `ToolCatalogSnapshot` with immutable `schema_hash` (SHA-256), `version`, `built_at`, and `docs: list[ToolDoc]`
- [ ] **CATALOG-03**: System implements `catalog.py` with `build_snapshot(registry)` converting `dict[str, ToolMapping]` → `ToolCatalogSnapshot`
- [ ] **CATALOG-04**: System extends `RetrievalConfig` with Phase 2 fields (`shadow_mode`, `scorer`, `fallback_tier`, `dynamic_k`) while maintaining backward compatibility with existing YAML configs

### Session Routing State (SESSION)

- [x] **SESSION-01**: System defines `SessionRoutingState` dataclass replacing monotonic guarantee with promote/demote hysteresis
- [x] **SESSION-02**: System promotes tools when rank within K-2 OR used via router 2/3 last turns
- [x] **SESSION-03**: System demotes tools only when rank below K+3 for 2 consecutive turns (max 3 demotions per turn)
- [x] **SESSION-04**: System maintains session isolation — `SessionRoutingState` is never shared across sessions

### Telemetry & Root Scanning (TELEM)

- [x] **TELEM-01**: System implements `telemetry/scanner.py` that scans declared MCP roots within allowlist (manifests, lockfiles, CI, containers, VCS state, README first 40 lines)
- [x] **TELEM-02**: System extracts typed sparse tokens (`manifest:Cargo.toml(3.0)`, `lang:rust(2.0)`, `ci:github-actions(1.5)`) into `RootEvidence` and `WorkspaceEvidence` dataclasses
- [x] **TELEM-03**: System enforces scan limits: max depth 6, max 10K entries, 150ms hard timeout per root
- [x] **TELEM-04**: System denies reading `.env*`, SSH keys, cloud credentials, arbitrary source files, or anything outside declared roots
- [x] **TELEM-05**: System implements `telemetry/monitor.py` with adaptive polling (5s → 10s → 20s → 30s) and significance threshold (cumulative ≥ 0.7 triggers re-score)

### Routing Tool (ROUTER)

- [x] **ROUTER-01**: System implements `routing_tool.py` as synthetic MCP tool registered via `_register_request_handlers()` in `MCPProxyServer`
- [x] **ROUTER-02**: Routing tool accepts `name` (exact tool lookup) and optional `describe` (return description) parameters per `PHASE2-PLAN.md` contract
- [x] **ROUTER-03**: Routing tool enum lists namespace-grouped, env-relevance ordered demoted tools
- [x] **ROUTER-04**: System never directly exposes more than 20 tools simultaneously; all tools beyond active set are accessible only through routing tool

### Fallback Ladder (FALLBACK)

- [x] **FALLBACK-01**: System implements 6-tier bounded fallback ladder — never exposes full catalog at any tier
- [x] **FALLBACK-02**: Terminal fallback (Tier 6) exposes conservative top-30 static defaults, not full `tool_to_server` registry

### Fusion & Dynamic K (FUSION)

- [x] **FUSION-01**: System implements weighted RRF in `fusion.py`: `final_rrf(tool) = α/(10+rank_env(t)) + (1-α)/(10+rank_conv(t))`
- [x] **FUSION-02**: System applies alpha-decay: `α = max(0.15, 0.85 · e^(-0.25·turn))` with overrides for explicit tool name (α=0.15) and roots change (α=0.80)
- [ ] **FUSION-03**: System uses dynamic K: base 15, +3 if polyglot workspace, cap 20

### Observability (OBS)

- [x] **OBS-01**: System implements `FileRetrievalLogger` extending existing `RetrievalLogger` ABC with JSONL per-turn `RankingEvent` logging
- [x] **OBS-02**: System emits `RankingEvent` per turn with: `session_id`, `turn_number`, `catalog_version`, `workspace_hash`, `alpha`, `active_k`, `fallback_tier`, `active_tool_ids`, `router_enum_size`, `scorer_latency_ms`

### Pipeline Wiring (WIRE)

- [ ] **WIRE-01**: System wires `RetrievalPipeline` into `MCPProxyServer.retrieval_pipeline` in `multi_mcp.py` (replacing TYPE_CHECKING-only import)
- [ ] **WIRE-02**: System wires catalog snapshot rebuild on `tool_to_server` changes via `register_client()`/`unregister_client()`

### Testing (TEST)

- [ ] **TEST-01**: `test_bmx_retriever.py` — unit tests for `BMXFRetriever` covering `rebuild_index`, `search_fields`, BMXF field weights
- [ ] **TEST-02**: `test_catalog_snapshot.py` — snapshot creation, versioning, schema_hash stability
- [x] **TEST-03**: `test_telemetry_scanner.py` — allowlist enforcement, scan budget limits, typed token extraction
- [x] **TEST-04**: `test_routing_tool.py` — routing tool registration, `name` lookup, `describe` response
- [x] **TEST-05**: `test_session_promote_demote.py` — promote/demote hysteresis, session isolation
- [x] **TEST-06**: `test_rrf_fusion.py` — weighted RRF correctness, alpha-decay at turns 0/1/5/10

## v2 Requirements (Deferred)

- PPMI token reweighting from usage logs (needs >50 sessions)
- Optional exploration injection (2 slots for rarely-used tools)
- Co-occurrence graph construction
- Neural reranker (needs tool count >500)
- TOON micro-descriptions
- Replay regression gate automation
- Canary traffic splitting controls

## Out of Scope

- GPU-based retrieval — CPU-only by design
- Process/env-var inspection — Privacy boundary (explicitly excluded)
- Mid-turn active-set mutation — Stability invariant
- K > 20 — Explicit non-goal per synthesized plan
- Full-catalog direct exposure — Core safety invariant

## Traceability

| Phase | Requirements Covered |
|-------|---------------------|
| Phase 0: Foundations | SCORE-01–04, CATALOG-01–04, WIRE-01–02, TEST-01–02 |
| Phase 1: Safe Lexical MVP | TELEM-01–04, ROUTER-01–04, FALLBACK-01–02, OBS-01–02, TEST-03–04 |
| Phase 2: Turn-by-Turn Adaptive | FUSION-01–03, SESSION-01–04, TELEM-05, TEST-05–06 |
| Phase 3: Rollout Hardening | Migration flags, alerting, dashboards |
| Phase 4: Post-GA Learning | v2 requirements above |
