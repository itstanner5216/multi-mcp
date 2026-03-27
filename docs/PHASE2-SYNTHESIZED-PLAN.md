# Multi-MCP Phase 2: Versioned Roots-Anchored BMXF Routing — Code-Accurate Synthesized Plan

> Synthesized from: `multi-mcp-report.md` (Plan A), `multi-mcp-synthesis.md` (Plan D), `multi-mcp-synthesized-plan2.md` (Plan E). Validated against the live codebase at `/home/tanner/Projects/multi-mcp`. Scoring upgraded from BM25/BM25+ to **BMX** (entropy-weighted BM25 successor, arXiv:2408.06643) using the custom `bmx.py` implementation at `/home/tanner/MCPServer/src/meta_mcp/rag/retrieval/bmx.py`.

---

## Evaluation Criteria

| # | Criterion | Weight | Rationale |
|---|-----------|-------:|-----------|
| 1 | Spec Correctness and Telemetry Realism | 16% | MCP `roots/list` provides only URIs + names + change notifications. Plans assuming more build the wrong architecture. |
| 2 | Cold Start Effectiveness | 16% | Turn-zero tool exposure is the core requirement. `RetrievalConfig(enabled=False)` exists precisely because there's no pre-turn signal today. |
| 3 | Scoring and Retrieval Architecture Quality | 14% | Must map to the existing `ToolRetriever` ABC, `RetrievalContext`, and `ScoredTool` types in `src/multimcp/retrieval/`. |
| 4 | Decision Completeness and Implementability | 14% | Must name exact files, classes, integration points, and BMX source (`bmx.py`). |
| 5 | Fallback and Failure-Mode Robustness | 10% | `PassthroughRetriever` returning all tools is the current failure mode. Must always produce bounded output. |
| 6 | Architectural Simplicity and Time-to-MVP | 8% | Ships atop existing `RelevanceRanker`, `TieredAssembler`, `SessionStateManager`. |
| 7 | Observability and Evaluation Readiness | 8% | `RetrievalLogger` ABC and `NullLogger` provide the hook — concrete implementation needed. |
| 8 | Security, Privacy, and Abuse Resistance | 6% | Root-scanned telemetry must not leak `.env`, keys, or branch names. |
| 9 | Extensibility and Maintainability | 4% | Future growth to 500+ tools and neural rankers without rewriting `src/multimcp/retrieval/`. |
| 10 | Migration and Rollout Safety | 4% | `RetrievalConfig.enabled` is the existing kill switch. `KeywordRetriever` and `PassthroughRetriever` remain available. |
| **Total** | | **100%** | |

---

## Individual Plan Analysis

### Plan A: "BM25+ Primary with RRF Fusion" (`multi-mcp-report.md`)

#### Strengths
- Roots telemetry three-tier signal taxonomy (manifests/lockfiles/CI → file extensions/IDE/git → gitignore/license/mtime) is the most actionable file-to-term mapping across all plans.
- BM25+ variant selection with δ=1.0 for short-document penalization is well-justified for 15-200 token tool descriptions. **[Superseded: BMX replaces BM25+ with entropy-weighted scoring and self-tuning parameters, eliminating δ entirely.]**
- Six-stage fallback chain replacing passthrough with "conservative top 30" at terminal position is the strongest failure-mode design.
- RRF for env/conv fusion (k=10) rather than parallel BM25+TF-IDF fusion is a sharp insight — lexical-vs-lexical fusion on 168 documents provides marginal benefit.
- Observability metrics (cold start hit rate, routing describe rate, top-K utilization) are concrete and implementable via the existing `RetrievalLogger` ABC.
- Full session lifecycle architecture (init → ongoing → post-session) maps to existing `SessionStateManager` + `RetrievalPipeline.on_tool_called()`.

#### Weaknesses
- Static heuristic weights (3.0/2.5/2.0/1.5/1.0/0.5) are presented without validation methodology.
- α-decay formula is untested against pathological cases (Python project, 20 turns of Kubernetes discussion).
- TOON micro-descriptions around router names conflict with the strict names-only router design from the existing `PHASE2-PLAN.md`.
- No BM25F/BMXF consideration despite tool corpus being clearly field-structured (`tool.name`, `server_name`, `tool.description`, `tool.inputSchema.properties`).

#### Gaps
- No MCP spec compliance analysis separating protocol-grounded from derived signals.
- No privacy/security analysis of telemetry extraction (.env leakage, git remote org exposure).
- No dynamic K adjustment strategy.
- No tool-catalog versioning or index invalidation when upstream servers change schemas (relevant: `MCPProxyServer.register_client()` already rebuilds `tool_to_server`).
- No migration path from existing `KeywordRetriever` to new scorer.

#### Incomplete Ideas
- "Tool co-occurrence graphs" — no schema, no query algorithm, no storage.
- "Session-type classification" — no classifier, no label set, no feature mapping.
- "Warm start from previous sessions" — no similarity function between environment fingerprints.

### Plan D: "Roots-Anchored BM25+ with Adaptive Scoring" (`multi-mcp-synthesis.md`)

#### Strengths
- Best existing synthesis: cherry-picks Plan A's fallback chain, Plan B's protocol correctness and typed sparse tokens, Plan C's dynamic K and adaptive polling.
- `WorkspaceEvidence` type with typed sparse token map (`manifest:Cargo.toml → 3.0`) is the most implementable intermediate representation.
- Three-phase phasing (2a MVP → 2b Refinement → 2c Learning) with concrete exit criteria.
- Latency budget allocation (10ms/100ms/5ms/20ms/5ms across pipeline stages).
- Exploration injection (2 slots for rarely-used tools) addresses cold-start feedback loops.

#### Weaknesses
- Single-tenant assumption conflicts with the fact that `MCPProxyServer` handles multiple server sessions via `_server_session`.
- Multi-root handling is vague: "per-root fingerprints merged with root-count weighting" is not a buildable algorithm.
- No tool-catalog versioning or snapshot mechanism.
- No shadow rollout, canary gates, or rollback conditions.
- References "MetaServer BM25 module" without examining the actual `BM25Index` class from MCPServer — the existing implementation is Okapi BM25 (not BM25+), uses `k1=1.5, b=0.75` defaults, and has a `build_index(chunks)` interface that takes `{"chunk_id": str, "text": str}` dicts, not `ToolMapping` objects. **[Resolved: BMX (`bmx.py`) replaces the original BM25 with entropy-weighted scoring, self-tuning α/β, and the same `build_index`/`search` interface.]**

#### Gaps
- No exact catalog snapshot versioning.
- No session isolation and concurrency rules for `SessionStateManager._sessions`.
- No strict allowlist/denylist telemetry policy.
- No replay dataset structure or regression gate.

#### Incomplete Ideas
- "PPMI refinement after >50 sessions" — no offline job, no deployment cadence.
- "Multi-root composition strategy" — placeholder, not algorithm.
- BMXF "wrapper implementation" — no specifics on how to adapt `BMXIndex` to score fields separately. **[Resolved in this plan.]**

### Plan E: "Versioned Roots-Anchored BMXF Routing" (`multi-mcp-synthesized-plan2.md`)

#### Strengths
- Hardens exactly where Plan D was weak: catalog snapshot versioning, telemetry allowlist/denylist, multi-root fusion algorithm, rollout feature flags with cutover gates.
- `ToolDoc` type with `retrieval_aliases` field solves vocabulary mismatch without neural retrieval.
- `ToolCatalogSnapshot` with immutable `schema_hash` and turn-boundary adoption is the most operationally sound design.
- `SessionRoutingState` with complete per-session state container prevents cross-session leakage.
- Promotion/demotion hysteresis (promote if within K-2 for current turn or used via router 2/3 last turns; demote only if below K+3 for 2 consecutive turns) prevents active-set churn.
- Concrete replay evaluation with `RankingEvent` type and required online metrics.
- Explicit non-goals: no process inspection, no env var inspection, no home-dir scanning, no mid-turn active-set mutation, no K > 20.

#### Weaknesses
- Still does not map to actual code. References generic TypeScript types rather than the Python dataclasses in `src/multimcp/retrieval/models.py`.
- Does not acknowledge the existing `BMXIndex` class or specify how to adapt it for field-weighted scoring.
- `retrieval_aliases` generation rules are described but no concrete mapping tables are provided for the actual 168 tools.
- Scan budgets (max depth 6, 10K entries, 100ms hard timeout) are plausible but untested against real monorepos.
- Doesn't reference the existing `KeywordRetriever.rebuild_index(registry)` pattern that any new retriever must follow.

#### Gaps
- No mapping of `ToolDoc` fields to actual `types.Tool` attributes (`tool.name`, `tool.description`, `tool.inputSchema`).
- No specification of where the routing tool integrates with `MCPProxyServer._register_request_handlers()`.
- No reference to the existing `_make_key(server_name, tool_name)` / `_split_key(key)` pattern for tool naming.
- No test strategy referencing the existing test suite (`tests/test_keyword_retriever.py`, `tests/test_retrieval_pipeline.py`, etc.).

#### Incomplete Ideas
- "Replay dataset structure" — describes the concept but not the file format, storage location, or generation script.
- "Operator runbook" — mentioned as a Phase 3 deliverable but no skeleton provided.

---

## Comparison Matrix

| # | Criterion (Weight) | Plan A | Plan D | Plan E |
|---|-------------------|--------|--------|--------|
| 1 | Spec Correctness and Telemetry Realism (16%) | 4 | 4 | **5** |
| 2 | Cold Start Effectiveness (16%) | 4 | **5** | **5** |
| 3 | Scoring and Retrieval Architecture Quality (14%) | 4 | **5** | **5** |
| 4 | Decision Completeness and Implementability (14%) | 3 | 4 | **4** |
| 5 | Fallback and Failure-Mode Robustness (10%) | **5** | **5** | **5** |
| 6 | Architectural Simplicity and Time-to-MVP (8%) | **4** | **4** | **4** |
| 7 | Observability and Evaluation Readiness (8%) | **4** | **4** | **5** |
| 8 | Security, Privacy, and Abuse Resistance (6%) | 2 | 4 | **4** |
| 9 | Extensibility and Maintainability (4%) | 3 | **4** | **4** |
| 10 | Migration and Rollout Safety (4%) | 2 | 3 | **5** |
| | **Weighted Total** | **3.72** | **4.36** | **4.68** |

**Weighted Totals:**

- Plan A: (4×.16)+(4×.16)+(4×.14)+(3×.14)+(5×.10)+(4×.08)+(4×.08)+(2×.06)+(3×.04)+(2×.04) = .64+.64+.56+.42+.50+.32+.32+.12+.12+.08 = **3.72**
- Plan D: (4×.16)+(5×.16)+(5×.14)+(4×.14)+(5×.10)+(4×.08)+(4×.08)+(4×.06)+(4×.04)+(3×.04) = .64+.80+.70+.56+.50+.32+.32+.24+.16+.12 = **4.36**
- Plan E: (5×.16)+(5×.16)+(5×.14)+(4×.14)+(5×.10)+(4×.08)+(5×.08)+(4×.06)+(4×.04)+(5×.04) = .80+.80+.70+.56+.50+.32+.40+.24+.16+.20 = **4.68**

---

## Universal Blind Spots

Things no plan adequately addressed when measured against the actual codebase:

1. **`BMXIndex` adaptation gap.** The BMX implementation at `bmx.py` takes `[{"chunk_id": str, "text": str}]` and returns `[(chunk_id, score)]`. None of the original plans specify the adapter layer that converts `dict[str, ToolMapping]` → BMX input chunks and BMX output scores → `list[ScoredTool]`. This is the critical integration glue.

2. **`MCPProxyServer.retrieval_pipeline` is TYPE_CHECKING only.** The import is guarded behind `if TYPE_CHECKING:` and the attribute is `Optional[RetrievalPipeline] = None`. No plan specifies the wiring code in `multi_mcp.py` that instantiates and attaches the pipeline.

3. **`_register_request_handlers()` routing tool registration.** The routing tool must be registered as an MCP tool via the handler pattern in `mcp_proxy.py`. No plan maps this to the existing handler registration code.

4. **`KeywordRetriever.rebuild_index(registry)` pattern.** The existing TF-IDF retriever has a `rebuild_index` method called with the full `dict[str, ToolMapping]` registry. The BMX retriever must follow this same pattern for index lifecycle management. None of the plans reference this.

5. **Existing test infrastructure.** 46+ test files exist in `tests/` including `test_keyword_retriever.py`, `test_retrieval_pipeline.py`, `test_retrieval_session.py`, `test_relevance_ranker.py`, `test_tiered_assembler.py`. No plan specifies test files for new components or how they integrate with the existing `pytest` + `pytest-asyncio` setup.

6. **`tool_to_server` key format.** All tool keys use `server_name__tool_name` (double underscore via `_make_key()`). The BMX index `chunk_id` must use this same key format. No plan makes this explicit.

7. **Lazy client pattern.** `ToolMapping.client` can be `None` (cached from YAML, server not yet connected). The retrieval pipeline must score tools regardless of client state — scoring operates on `tool.name` and `tool.description`, not client availability.

8. **`mcp>=1.26.0` roots API.** The actual `mcp` Python package version in `pyproject.toml` is `>=1.26.0`. No plan verifies whether this version exposes the roots request/notification API or specifies how to call `roots/list` from the server side.

9. **Existing `RetrievalConfig` fields.** The config has `enabled: bool`, `top_k: int`, `full_description_count: int`, `anchor_tools: list[str]`. New fields (fallback tier, dynamic K, telemetry settings) must extend this dataclass without breaking existing YAML configs.

---

## Clarifying Questions

No questions block the synthesis. Assumptions are locked:

| Question I Would Ask | Assumption I'm Making |
|---------------------|----------------------|
| Does `mcp>=1.26.0` expose `roots/list` and `notifications/roots/list_changed` on the server side? | Yes — if not, we wrap the raw JSON-RPC call. Roots capability is in the MCP spec since 2025-11-25. |
| Is the existing `BMXIndex` from `bmx.py` pure Python with no external deps? | Yes — confirmed by code review. Uses only `math`, `re`, `collections.Counter`, `dataclasses`. |
| Is the router contract (`request_tool` with `name` + optional `describe`) fixed? | Yes — per `PHASE2-PLAN.md` in the project root. |
| Can `SessionStateManager` be extended to support demotion (breaking monotonic guarantee)? | Yes for Phase 2 — the monotonic guarantee was a Phase 1 safety constraint that must evolve for promote/demote. |
| Is `RetrievalConfig.enabled=False` the only kill switch needed? | Yes — it already exists and all pipeline code checks it. |

---

## Plan Rankings

| Rank | Plan | Score | Got Most Right | Limiting Factor |
|------|------|------:|----------------|-----------------|
| **1** | Plan E | 4.68 | Catalog versioning, telemetry allowlist, multi-root algorithm, rollout gates. | Not mapped to actual Python code, classes, or integration points. |
| **2** | Plan D | 4.36 | Best synthesis baseline, `WorkspaceEvidence`, phased architecture. | Vague on versioning, rollout, session isolation, BMX adaptation. |
| **3** | Plan A | 3.72 | Best raw retrieval architecture, signal taxonomy, fallback chain. | No protocol precision, no BMXF, no migration path. |

---

## Synthesized Plan: "Code-Grounded Roots-Anchored BMXF Routing"

### Assumptions

| # | Assumption |
|---|-----------|
| 1 | MCP `roots/list` provides only root URIs, optional names, and optional `roots/list_changed` notifications. All derived signals require active scanning. |
| 2 | CPU-only. No GPU. No external API calls in the scoring path. |
| 3 | Tool count 168 now, ceiling 500. Neural retrieval deferred to Phase 3. |
| 4 | `BMXIndex` from `bmx.py` is copied into the project and adapted. It is the entropy-weighted BMX algorithm (arXiv:2408.06643) with self-tuning α/β parameters, sigmoid TF saturation, and built-in score normalization. No BM25+ δ needed — BMX's restructured length normalization subsumes that fix. |
| 5 | Existing retrieval module (`KeywordRetriever`, `PassthroughRetriever`, `RelevanceRanker`, `TieredAssembler`, `SessionStateManager`, `RetrievalPipeline`) remains unchanged. New components extend, not replace. |
| 6 | Single session per server instance is typical but session state must be session-scoped via `SessionRoutingState`. |
| 7 | TOON compression, exploration injection, and offline learning are post-GA. |
| 8 | The routing tool is a new synthetic MCP tool registered via `MCPProxyServer`. |

### Cherry-Pick Registry

| Component | Source | Rationale |
|-----------|--------|-----------|
| Three-tier signal taxonomy | Plan A | Most complete file-to-term mapping with concrete predictive tiers |
| Protocol-grounded vs derived telemetry | Plan B (via D/E) | Correct separation of what `roots/list` provides vs what must be derived |
| Typed sparse tokens (`manifest:Cargo.toml`, `lang:rust`) | Plan B (via D/E) | Most debuggable format; feeds directly into BMX |
| BMX base implementation | `bmx.py` | Already exists as pure Python; entropy-weighted scoring with self-tuning parameters outperforms BM25/BM25+ by ~+1.15 nDCG@10 on BEIR |
| BMX entropy-weighted similarity | BMX paper (arXiv:2408.06643) | `β·E(qᵢ)·S(Q,D)` term rewards holistic query coverage; sigmoid TF saturation handles keyword spam; replaces BM25+ δ |
| BMXF field weighting | Plan B/E (adapted) | `tool_name(3.0)` > `namespace(2.5)` > `description(1.0)` > `parameter_names(0.5)` — same field structure, BMX scorer per field |
| Weighted RRF for env/conv fusion (k=10) | Plan A | Operates on ranks, avoids score calibration problems |
| Six-stage bounded fallback ladder | Plan A + E | Strongest failure-mode architecture; never exposes full catalog |
| `ToolCatalogSnapshot` with `schema_hash` | Plan E | Immutable versioned index, turn-boundary adoption |
| `SessionRoutingState` | Plan E | Complete per-session state container preventing cross-session leakage |
| Promotion/demotion hysteresis | Plan E | Prevents active-set churn without suppressing legitimate changes |
| Dynamic K (base 15, max 20) | Plan C/D/E | Adapts to ambiguity without unbounded growth |
| Telemetry allowlist/denylist | Plan E | Strict passive scan boundary |
| `retrieval_aliases` on tool docs | Plan E | Reduces vocabulary mismatch without neural retrieval |
| Adaptive polling with significance thresholds | Plan C/E | Avoids over-scanning stable environments |
| `RankingEvent` logging | Plan E | Per-turn structured event for replay evaluation |
| Migration feature flags | Plan E | `shadow_mode` in `RetrievalConfig` |
| Multi-root per-root scoring + weighted RRF fusion | Plan E | Replaces flattened bag with per-root evidence composition |
| Scan budgets (depth 6, 10K entries, 150ms hard) | Plan E | Prevents monorepo scan from blocking session init |
| `BMXIndex` → `ToolRetriever` adapter pattern | Original | Bridges universal blind spot #1 — the critical integration glue |
| `_register_request_handlers()` routing tool wiring | Original | Bridges universal blind spot #3 — maps to existing handler code |
| Test file naming parallel to existing suite | Original | Bridges universal blind spot #5 — `test_bmx_retriever.py` alongside `test_keyword_retriever.py` |

### Architecture Overview

```
CODEBASE MAPPING:

src/multimcp/
├── retrieval/                          # EXISTING package
│   ├── __init__.py                     # UPDATE: export new classes
│   ├── base.py                         # UNCHANGED: ToolRetriever ABC, PassthroughRetriever
│   ├── models.py                       # UPDATE: extend RetrievalConfig, add new dataclasses
│   ├── keyword.py                      # UNCHANGED: KeywordRetriever (TF-IDF fallback)
│   ├── bmx_retriever.py               # NEW: BMXFRetriever(ToolRetriever)
│   ├── bmx_index.py                   # NEW: copied BMXIndex from bmx.py
│   ├── ranker.py                       # UNCHANGED: RelevanceRanker
│   ├── assembler.py                    # UPDATE: add routing-tool tier
│   ├── session.py                      # UPDATE: replace monotonic with promote/demote
│   ├── pipeline.py                     # UPDATE: wire BMXF, fallback chain, RRF blend
│   ├── namespace_filter.py             # UNCHANGED: compute_namespace_boosts()
│   ├── logging.py                      # UPDATE: implement FileRetrievalLogger
│   ├── telemetry/                      # NEW subpackage
│   │   ├── __init__.py
│   │   ├── scanner.py                  # Root filesystem scanner with allowlist
│   │   ├── evidence.py                 # RootEvidence, WorkspaceEvidence dataclasses
│   │   ├── tokens.py                   # Signal → typed sparse token generation
│   │   └── monitor.py                  # Change detection, polling, debounce
│   ├── routing_tool.py                 # NEW: RoutingTool — synthetic MCP tool
│   ├── catalog.py                      # NEW: ToolCatalogSnapshot, ToolDoc
│   └── fusion.py                       # NEW: Weighted RRF, alpha-decay blend
├── mcp_proxy.py                        # UPDATE: wire retrieval_pipeline, register routing tool
├── multi_mcp.py                        # UPDATE: instantiate pipeline with config
└── yaml_config.py                      # UPDATE: retrieval config section

tests/
├── test_bmx_retriever.py              # NEW
├── test_telemetry_scanner.py          # NEW
├── test_routing_tool.py               # NEW
├── test_catalog_snapshot.py           # NEW
├── test_session_promote_demote.py     # NEW
├── test_rrf_fusion.py                 # NEW
└── ... (existing 46+ tests unchanged)
```

```
EXECUTION FLOW:

SESSION INIT (target: <400ms total)
├── [immediate] Client connects, MCPProxyServer initializes
├── [if supported] Server requests roots/list from client
│   ├── Protocol layer: URIs + names + listChanged capability
│   └── Derived layer: allowlisted filesystem scan within declared roots
│       ├── Tier 1: manifests, lockfiles, CI/CD, containers, cloud, DB configs
│       ├── Tier 2: file extensions (sampled), IDE configs, git state (bucketed)
│       ├── Tier 3: .gitignore patterns, license, mtime
│       └── Scan limits: max depth 6, max 10K entries, 150ms hard timeout per root
├── Signal extraction → RootEvidence[] → WorkspaceEvidence
│   ├── Typed sparse tokens: manifest:Cargo.toml(3.0), lang:rust(2.0), ci:github-actions(1.5)
│   └── Confidence: 0.0-1.0 from signal diversity + pattern match
├── BMXF scoring (environment query only)
│   ├── Field weights: tool_name(3.0), namespace(2.5), retrieval_aliases(1.5),
│   │                  description(1.0), parameter_names(0.5)
│   ├── BMX params: α auto-tuned from avgdl (clamped 0.5–1.5), β = 1/log(1+N)
│   │   env query mode: alpha_override=0.5 (short tool descriptions → low avgdl)
│   └── Confidence gating: low confidence → expand K, blend with frequency defaults
├── Ranking + tiered assembly
│   ├── Top-K fully exposed with full schemas (via TieredAssembler)
│   ├── Remaining → routing tool name registry (namespace-grouped, env-relevance ordered)
│   └── Dynamic K: base 15, +3 if polyglot, cap 20
└── Expose initial tool set to model via _list_tools()

EACH CONVERSATION TURN:
├── Extract conversation terms (stopword removal, noun phrases, tool verbs)
├── Switch to NL query BMX params (alpha_override=None for auto-tune, normalize_scores=True)
├── Compute blended score via weighted RRF (k=10):
│    final_rrf(tool) = α/(10+rank_env(t)) + (1-α)/(10+rank_conv(t))
│    α = max(0.15, 0.85 · e^(-0.25·turn))
│    Override: explicit tool name + conv_confidence ≥ 0.70 → α = 0.15
│    Override: roots/list_changed → α = 0.80
├── Promote/demote with hysteresis at turn boundary
│    Promote: rank within K-2 OR used via router 2/3 last turns
│    Demote: rank below K+3 for 2 consecutive turns, max 3 per turn
├── Update routing tool enum (remove promoted, add demoted)
└── Emit RankingEvent to logger

BACKGROUND:
├── roots/list_changed → immediate re-scan + re-score
├── Adaptive polling: 5s (active) → 10s → 20s → 30s (stable)
├── Significance threshold: cumulative ≥ 0.7 triggers re-score
├── Backpressure: if ranking p95 > 75ms, freeze polling to 15s minimum
└── Catalog snapshot rebuild on tool_to_server changes (register/unregister)
```

#### Core Invariants

| Invariant | Rule |
|-----------|------|
| Full exposure safety | No execution path may expose all tools. Max directly exposed = 20. Remaining in routing tool. |
| Passive telemetry boundary | No scan may read outside declared roots. |
| Mid-turn stability | Active set and router enum do not change during a model turn. |
| Snapshot pinning | Every turn is pinned to one `ToolCatalogSnapshot.version`. |
| Session isolation | `SessionRoutingState` is never shared across sessions. |
| Bounded degradation | Every fallback tier returns a bounded, valid active set plus router. |

### Implementation Details

#### 1. `bmx_index.py` — Copied from `bmx.py`

**Source:** `bmx.py` (BMXIndex — entropy-weighted BM25 successor, pure Python, ~400 lines)

**Copy to:** `src/multimcp/retrieval/bmx_index.py`

**BMXIndex interface (identical shape to original BM25Index):**
- `BMXIndex` dataclass with auto-tuned `α` (from avgdl) and `β` (from corpus size)
- Optional overrides: `alpha_override: float | None`, `beta_override: float | None`
- `build_index(chunks: list[dict])` — expects `{"chunk_id": str, "text": str}`
- `search(query: str, top_k: int, normalize: bool | None) -> list[tuple[str, float]]`
- `update_index(chunk_id, text)`, `remove_from_index(chunk_id)`
- `_tokenize(text)` — lowercase, regex split `[a-z0-9_]+`, filter len>1
- `_score_document()` — BMX formula: `IDF·[tf·(α+1)] / [tf + α·|D|/avgdl + α·Ē] + β·E(qᵢ)·S(Q,D)`
- IDF: `log((N - df + 0.5) / (df + 0.5) + 1)` (same Lucene variant as BM25)
- Score normalization: `score / (m · [log(1 + (N-0.5)/1.5) + 1.0])` maps to [0, 1]

**No modifications needed for multi-mcp** — BMXIndex is already a drop-in replacement for BM25Index with the same `build_index`/`search`/`update_index`/`remove_from_index` API. Key advantages over the original BM25:

1. **Self-tuning parameters** — α and β are computed from corpus statistics (avgdl, N), eliminating manual k₁/b tuning. For the tool corpus (~15-200 token descriptions, ~168-500 docs), α will auto-set to ~0.5 and β to ~0.19.

2. **Entropy-weighted similarity** — the `β·E(qᵢ)·S(Q,D)` term rewards documents matching more query tokens, with rare/informative tokens weighted higher. This directly helps multi-token environment queries like "manifest:Cargo.toml lang:rust ci:github-actions".

3. **Sigmoid TF saturation** — term frequencies are mapped through sigmoid for entropy computation, capping keyword-stuffed tool descriptions (a tool repeating "file" 10× scores similarly to one mentioning it twice).

4. **Built-in score normalization** — `search(..., normalize=True)` maps scores to [0, 1], enabling cross-query comparison in RRF fusion without score calibration hacks.

**Add BMXF field-weighted wrapper methods:**
```python
def build_field_index(self, tool_docs: list["ToolDoc"]) -> None:
    """Build separate BMX sub-indexes per field."""
    self._field_indexes: dict[str, BMXIndex] = {}
    self._field_weights = {
        "tool_name": 3.0,
        "namespace": 2.5,
        "retrieval_aliases": 1.5,
        "description": 1.0,
        "parameter_names": 0.5,
    }
    for field_name in self._field_weights:
        field_idx = BMXIndex(
            alpha_override=self.alpha_override,
            beta_override=self.beta_override,
            normalize_scores=self.normalize_scores,
        )
        chunks = []
        for doc in tool_docs:
            text = getattr(doc, field_name, "") or ""
            if isinstance(text, list):
                text = " ".join(text)
            chunks.append({"chunk_id": doc.tool_key, "text": text})
        field_idx.build_index(chunks)
        self._field_indexes[field_name] = field_idx

def search_fields(self, query: str, top_k: int = 30) -> list[tuple[str, float]]:
    """Score across all fields with weighted sum."""
    combined: dict[str, float] = {}
    for field_name, weight in self._field_weights.items():
        field_idx = self._field_indexes.get(field_name)
        if not field_idx:
            continue
        results = field_idx.search(query, top_k=top_k * 2)
        for chunk_id, score in results:
            combined[chunk_id] = combined.get(chunk_id, 0.0) + weight * score
    sorted_results = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:top_k]
```

5. **All existing BMXIndex methods preserved:** `update_index`, `remove_from_index`, `get_index_stats`, `clear`. These enable incremental index updates when `tool_to_server` changes.

#### 2. `models.py` — Extended Data Models

Added to `src/multimcp/retrieval/models.py` (existing file, 37 lines currently). All new dataclasses use `from __future__ import annotations` and `field(default_factory=...)` matching existing style.

```python
# === NEW: Tool catalog types ===

@dataclass
class ToolDoc:
    """Canonical retrieval document for a single tool.
    Maps to ToolMapping: tool_key from _make_key(), fields from types.Tool."""
    tool_key: str                  # server_name__tool_name
    tool_name: str                 # tool.name (without server prefix)
    namespace: str                 # server_name
    description: str               # tool.description or ""
    parameter_names: str           # space-joined keys from tool.inputSchema.properties
    retrieval_aliases: str         # curated lexical aliases, space-joined

@dataclass
class ToolCatalogSnapshot:
    """Immutable versioned index of all tools."""
    version: str
    schema_hash: str               # SHA-256 of sorted canonical tool docs
    built_at: float
    docs: list[ToolDoc] = field(default_factory=list)

# === NEW: Telemetry types ===

@dataclass
class RootEvidence:
    """Evidence derived from scanning a single MCP root."""
    root_uri: str
    root_name: Optional[str] = None
    tokens: dict[str, float] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    fingerprint_hash: str = ""
    partial_scan: bool = False

@dataclass
class WorkspaceEvidence:
    """Composition of all root evidence for this session."""
    roots: list[RootEvidence] = field(default_factory=list)
    workspace_confidence: float = 0.0
    merged_tokens: dict[str, float] = field(default_factory=dict)
    workspace_hash: str = ""

# === NEW: Session routing state ===

@dataclass
class SessionRoutingState:
    """Per-session mutable state for ranking and routing.
    Replaces the monotonic guarantee in SessionStateManager for Phase 2."""
    session_id: str
    catalog_version: str = ""
    turn_number: int = 0
    env_hash: Optional[str] = None
    env_confidence: float = 0.0
    conv_confidence: float = 0.0
    alpha: float = 0.85
    active_k: int = 15
    fallback_tier: int = 1
    active_tool_ids: list[str] = field(default_factory=list)
    router_enum_tool_ids: list[str] = field(default_factory=list)
    recent_router_describes: list[str] = field(default_factory=list)
    recent_router_proxies: list[str] = field(default_factory=list)
    last_rank_scores: dict[str, float] = field(default_factory=dict)
    consecutive_low_rank: dict[str, int] = field(default_factory=dict)

# === NEW: Observability ===

@dataclass
class RankingEvent:
    """Structured log entry for every ranking decision."""
    session_id: str
    turn_number: int
    catalog_version: str
    workspace_hash: Optional[str] = None
    workspace_confidence: float = 0.0
    conv_confidence: float = 0.0
    alpha: float = 0.0
    active_k: int = 0
    fallback_tier: int = 0
    active_tool_ids: list[str] = field(default_factory=list)
    router_enum_size: int = 0
    direct_tool_calls: list[str] = field(default_factory=list)
    router_describes: list[str] = field(default_factory=list)
    router_proxies: list[str] = field(default_factory=list)
    scorer_latency_ms: float = 0.0

# === UPDATED: RetrievalConfig (extends existing, backward compatible) ===

@dataclass
class RetrievalConfig:
    """Pipeline configuration. New fields have defaults for backward compat."""
    enabled: bool = False
    top_k: int = 15
    full_description_count: int = 3
    anchor_tools: list[str] = field(default_factory=list)
    # Phase 2 additions:
    scorer: str = "bmxf"           # "bmxf" | "keyword" | "passthrough"
    max_k: int = 20
    enable_routing_tool: bool = True
    enable_telemetry: bool = True
    telemetry_poll_interval: int = 30
    shadow_mode: bool = False
```

#### 3. `bmx_retriever.py` — Primary Retriever

New file at `src/multimcp/retrieval/bmx_retriever.py`. Implements `ToolRetriever` ABC (from `base.py`). Follows `KeywordRetriever.rebuild_index(registry)` pattern.

```python
"""BMXF field-weighted retriever implementing the ToolRetriever interface.

Adapts BMXIndex (from bmx.py) to score ToolMapping objects
using field-weighted BMX scoring across tool_name, namespace,
description, parameter_names, and retrieval_aliases.

BMX advantages over BM25 for tool retrieval:
- Self-tuning α/β eliminates per-corpus parameter tuning
- Entropy-weighted similarity rewards multi-token query coverage
- Sigmoid TF saturation handles keyword-heavy tool descriptions
- Built-in score normalization enables clean RRF fusion
"""

class BMXFRetriever(ToolRetriever):
    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config
        self._index = BMXIndex()  # α/β auto-tuned from corpus stats
        self._tool_docs: dict[str, ToolDoc] = {}

    def rebuild_index(self, registry: dict[str, "ToolMapping"]) -> None:
        """Rebuild BMXF index from tool registry.
        Mirrors KeywordRetriever.rebuild_index() lifecycle pattern.
        Uses _make_key() format: tool keys are server_name__tool_name."""
        self._tool_docs.clear()
        for key, mapping in registry.items():
            ns, name = key.split("__", 1) if "__" in key else ("", key)
            param_names = _extract_param_names(mapping.tool.inputSchema)
            aliases = _generate_aliases(ns, name)
            self._tool_docs[key] = ToolDoc(
                tool_key=key,
                tool_name=name,
                namespace=ns,
                description=mapping.tool.description or "",
                parameter_names=" ".join(param_names),
                retrieval_aliases=" ".join(aliases),
            )
        self._index.build_field_index(list(self._tool_docs.values()))

    async def retrieve(
        self, context: RetrievalContext, candidates: list["ToolMapping"],
    ) -> list[ScoredTool]:
        """Score candidates against context query using BMXF.
        Returns ScoredTool list compatible with RelevanceRanker and TieredAssembler."""
        if not context.query:
            return [ScoredTool(
                tool_key=f"{m.server_name}__{m.tool.name}",
                tool_mapping=m, score=0.5, tier="full",
            ) for m in candidates[:self._config.top_k]]

        candidate_keys = {f"{m.server_name}__{m.tool.name}": m for m in candidates}
        results = self._index.search_fields(context.query, top_k=self._config.top_k * 2)

        boosts = compute_namespace_boosts(candidate_keys, server_hint=context.server_hint)
        scored = []
        for chunk_id, score in results:
            if chunk_id not in candidate_keys:
                continue
            boost = boosts.get(chunk_id, 1.0)
            scored.append(ScoredTool(
                tool_key=chunk_id,
                tool_mapping=candidate_keys[chunk_id],
                score=score * boost,
                tier="full",
            ))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:self._config.top_k]
```

**`_generate_aliases()` curated mappings** (covers the three actual configured servers plus common patterns):

```python
NAMESPACE_ALIASES = {
    "github": ["repository", "pull_request", "issue", "git", "code_review", "branch", "commit"],
    "brave-search": ["web_search", "internet", "lookup", "find", "query"],
    "context7": ["documentation", "library", "docs", "api_reference", "examples"],
    "docker": ["container", "image", "compose", "deploy", "service"],
    "filesystem": ["file", "directory", "read", "write", "path", "folder"],
    "shell": ["terminal", "command", "bash", "exec", "run", "process"],
    "slack": ["message", "channel", "chat", "notification"],
    "npm": ["package", "install", "node", "dependency"],
    "pip": ["package", "install", "python", "dependency"],
    "cargo": ["crate", "build", "rust", "compile"],
    "kubectl": ["kubernetes", "pod", "deployment", "service", "cluster"],
    "terraform": ["infrastructure", "cloud", "provision", "iac"],
}

ACTION_ALIASES = {
    "list": ["get", "fetch", "show", "enumerate"],
    "create": ["add", "new", "make", "insert"],
    "search": ["find", "query", "lookup"],
    "delete": ["remove", "destroy", "drop"],
    "update": ["edit", "modify", "change", "patch"],
    "run": ["execute", "invoke", "start"],
    "get": ["fetch", "read", "retrieve"],
}
```

#### 4. `telemetry/scanner.py` — Allowlisted Root Scanner

```python
"""Allowlisted filesystem scanner for MCP roots.
Never follows symlinks outside root. Never reads denied patterns."""

ALLOWED_MANIFESTS = {
    "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "Gemfile", "composer.json",
}
ALLOWED_LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
}
DENIED_PATTERNS = {".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519"}

MAX_DEPTH = 6
MAX_ENTRIES = 10_000
HARD_TIMEOUT_MS = 150
```

#### 5. `telemetry/tokens.py` — Token Generation with Abuse Resistance

```python
TOKEN_WEIGHTS = {
    "manifest:": 3.0, "lock:": 2.5, "framework:": 2.5,
    "lang:": 2.0, "ci:": 1.5, "container:": 1.5,
    "infra:": 1.5, "db:": 1.5, "vcs:": 1.0,
    "layout:": 0.75, "readme:": 0.5,
}

MANIFEST_LANGUAGE_MAP = {
    "package.json": ["javascript", "typescript", "npm", "node"],
    "Cargo.toml": ["rust", "cargo", "crate"],
    "pyproject.toml": ["python", "pip", "pypi"],
    "go.mod": ["golang", "go"],
    "pom.xml": ["java", "maven"],
    "build.gradle": ["java", "kotlin", "gradle"],
    "Gemfile": ["ruby", "gem", "bundler"],
    "composer.json": ["php", "composer"],
}

# Abuse resistance:
MAX_FAMILY_CONTRIBUTION = 0.35  # No single token family > 35% of total env score
MAX_README_TOKENS = 20          # Cap readme-derived tokens
# Raw dependency names do NOT flow into ranking unless they match a curated
# dependency-to-capability map. Unknown deps stored as diagnostics only.
```

#### 6. `fusion.py` — RRF and Alpha-Decay

```python
"""Reciprocal Rank Fusion and alpha-decay blending."""

import math
from .models import ScoredTool

RRF_K = 10

def weighted_rrf(
    env_ranked: list[ScoredTool],
    conv_ranked: list[ScoredTool],
    alpha: float,
) -> list[ScoredTool]:
    """Fuse environment and conversation rankings via weighted RRF."""
    env_ranks = {t.tool_key: i for i, t in enumerate(env_ranked)}
    conv_ranks = {t.tool_key: i for i, t in enumerate(conv_ranked)}
    all_keys = set(env_ranks) | set(conv_ranks)
    max_rank = max(len(env_ranked), len(conv_ranked)) + 1

    # Collect tool_mapping references for output
    tool_map = {}
    for t in env_ranked:
        tool_map[t.tool_key] = t.tool_mapping
    for t in conv_ranked:
        tool_map.setdefault(t.tool_key, t.tool_mapping)

    fused = []
    for key in all_keys:
        env_r = env_ranks.get(key, max_rank)
        conv_r = conv_ranks.get(key, max_rank)
        score = alpha / (RRF_K + env_r) + (1 - alpha) / (RRF_K + conv_r)
        fused.append(ScoredTool(
            tool_key=key, tool_mapping=tool_map[key], score=score, tier="full",
        ))

    fused.sort(key=lambda s: s.score, reverse=True)
    return fused

def compute_alpha(
    turn: int, workspace_confidence: float, conv_confidence: float,
    roots_changed: bool = False, explicit_tool_mention: bool = False,
) -> float:
    """Alpha-decay with confidence gating and overrides."""
    base = max(0.15, 0.85 * math.exp(-0.25 * turn))
    if workspace_confidence < 0.45:
        base = max(0.15, base - 0.20)
    if explicit_tool_mention and conv_confidence >= 0.70:
        base = 0.15
    if roots_changed:
        base = max(base, 0.80)
    return base
```

#### 7. `routing_tool.py` — Synthetic MCP Routing Tool

```python
"""Routing tool for collapsed (demoted) tools.

Registered as a synthetic MCP tool via MCPProxyServer.
Holds bare names of all tools not in the active top-K.
Model can describe or proxy-call."""

from mcp import types

ROUTING_TOOL_NAME = "request_tool"
ROUTING_TOOL_KEY = "__routing__request_tool"

def build_routing_tool_schema(demoted_tool_ids: list[str]) -> types.Tool:
    """Build the routing tool's MCP Tool with dynamic enum."""
    return types.Tool(
        name=ROUTING_TOOL_NAME,
        description=(
            "Access tools not in your active set. "
            "Use describe=true to get full schema, or provide arguments to call directly."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name (server__tool format)",
                    "enum": demoted_tool_ids,
                },
                "describe": {
                    "type": "boolean",
                    "description": "If true, return tool schema instead of calling",
                    "default": False,
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass when describe=false",
                    "default": {},
                },
            },
            "required": ["name"],
        },
    )

def format_namespace_grouped(tool_ids: list[str], env_namespaces: list[str]) -> list[str]:
    """Order tool IDs: env-relevant namespaces first, then alphabetical."""
    groups: dict[str, list[str]] = {}
    for tid in tool_ids:
        ns = tid.split("__", 1)[0] if "__" in tid else ""
        groups.setdefault(ns, []).append(tid)
    ordered = []
    for ns in env_namespaces:
        if ns in groups:
            ordered.extend(sorted(groups.pop(ns)))
    for ns in sorted(groups.keys()):
        ordered.extend(sorted(groups[ns]))
    return ordered
```

#### 8. `catalog.py` — Tool Catalog Snapshot

```python
"""Immutable versioned tool catalog snapshots."""

import hashlib, json, time
from .models import ToolDoc, ToolCatalogSnapshot

_version_counter = 0

def build_snapshot(registry: dict[str, "ToolMapping"]) -> ToolCatalogSnapshot:
    """Build immutable catalog snapshot from live tool_to_server registry."""
    global _version_counter
    _version_counter += 1
    docs = []
    for key, mapping in sorted(registry.items()):
        ns, name = key.split("__", 1) if "__" in key else ("", key)
        props = mapping.tool.inputSchema or {}
        param_names = list(props.get("properties", {}).keys()) if isinstance(props, dict) else []
        docs.append(ToolDoc(
            tool_key=key, tool_name=name, namespace=ns,
            description=mapping.tool.description or "",
            parameter_names=" ".join(param_names),
            retrieval_aliases="",  # Populated by BMXFRetriever._generate_aliases()
        ))
    canonical = json.dumps(
        [{"k": d.tool_key, "d": d.description, "p": d.parameter_names} for d in docs],
        sort_keys=True,
    )
    return ToolCatalogSnapshot(
        version=str(_version_counter),
        schema_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        built_at=time.time(),
        docs=docs,
    )
```

#### 9. Integration Points in Existing Code

**`mcp_proxy.py` changes (minimal, surgical):**

```python
# In MCPProxyServer.__init__(), ADD after self.retrieval_pipeline line:
self._routing_tool_schema: Optional[types.Tool] = None

# In _register_request_handlers(), ADD routing tool call handler:
# When a tool call comes in for "request_tool", dispatch to
# routing_tool.handle_call() which either:
#   describe=True → return tool schema from tool_to_server[name].tool
#   describe=False → forward to actual tool via existing _call_tool() logic

# In _list_tools() (the MCP tools/list handler), ADD:
# If self.retrieval_pipeline and self.retrieval_pipeline.config.enabled:
#   tools = await self.retrieval_pipeline.get_tools_for_list(session_id)
#   if self._routing_tool_schema:
#       tools.append(self._routing_tool_schema)
#   return tools
```

**`multi_mcp.py` changes (pipeline wiring):**

```python
# After proxy creation and tool_to_server population, ADD:

from src.multimcp.retrieval.bmx_retriever import BMXFRetriever
from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.ranker import RelevanceRanker
from src.multimcp.retrieval.assembler import TieredAssembler
from src.multimcp.retrieval.logging import NullLogger  # or FileRetrievalLogger
from src.multimcp.retrieval.pipeline import RetrievalPipeline

config = RetrievalConfig(enabled=True, top_k=15, scorer="bmxf")
retriever = BMXFRetriever(config)
retriever.rebuild_index(proxy.tool_to_server)

pipeline = RetrievalPipeline(
    retriever=retriever,
    session_manager=SessionStateManager(config),
    logger=NullLogger(),  # Replace with FileRetrievalLogger in Phase 1
    config=config,
    tool_registry=proxy.tool_to_server,
    ranker=RelevanceRanker(),
    assembler=TieredAssembler(),
)
proxy.retrieval_pipeline = pipeline
```

**`session.py` changes (promote/demote):**

Replace monotonic `add_tools()` with `promote()` and `demote()`:

```python
def promote(self, session_id: str, tool_keys: list[str]) -> list[str]:
    """Add tools to active set at turn boundary. Returns newly promoted keys."""
    session = self._sessions.get(session_id)
    if session is None:
        return []
    new_keys = [k for k in tool_keys if k not in session]
    session.update(new_keys)
    return new_keys

def demote(self, session_id: str, tool_keys: list[str],
           used_this_turn: set[str], max_per_turn: int = 3) -> list[str]:
    """Remove tools from active set with safety constraints.
    Never demotes tools used this turn. Max 3 demotions per turn."""
    session = self._sessions.get(session_id)
    if session is None:
        return []
    safe_to_demote = [k for k in tool_keys if k in session and k not in used_this_turn]
    demoted = safe_to_demote[:max_per_turn]
    session -= set(demoted)
    return demoted
```

#### 10. Fallback Ladder

| Tier | Trigger | Action | Scorer |
|------|---------|--------|--------|
| 1 | Normal operation | BMXF env + conversation blend | `BMXFRetriever` |
| 2 | Conversation query weak or failed | BMXF environment-only | `BMXFRetriever` |
| 3 | BMXF index unavailable or corrupt | TF-IDF environment-only | `KeywordRetriever` |
| 4 | No usable scorer, but `project_type_guess` confident | Static category defaults | Hardcoded map |
| 5 | Static type weak, per-user 7-day prior available | Time-decayed frequency prior | Usage log |
| 6 | Everything above unavailable | Universal 12-tool set + routing tool | Hardcoded |

**Static category defaults** (Phase 1 deliverable, curated once, versioned):

```yaml
categories:
  node_web:
    always: [filesystem, shell, web_search]
    likely: [github, npm, docker, jest]
  python_web:
    always: [filesystem, shell, web_search]
    likely: [github, pip, docker, pytest]
  rust_cli:
    always: [filesystem, shell, web_search]
    likely: [github, cargo]
  infrastructure:
    always: [filesystem, shell, web_search]
    likely: [terraform, kubectl, docker, helm]
  generic:
    always: [filesystem, shell, web_search, github]
```

No fallback tier exposes the full `tool_to_server` registry. Maximum directly exposed = 20.

#### 11. Telemetry Allowlist

| Category | Allowed Files | Parse Rule |
|----------|--------------|------------|
| Manifests | `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `Gemfile`, `composer.json` | Ecosystem + dependency names only |
| Lockfiles | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `Cargo.lock`, `go.sum` | Presence and package names only |
| Framework | `next.config.*`, `vite.config.*`, `prisma/schema.prisma`, `angular.json` | Detect family only |
| CI | `.github/workflows/*`, `.gitlab-ci.yml`, `.circleci/config.yml`, `Jenkinsfile` | Provider + deploy/test keywords only |
| Container | `Dockerfile`, `docker-compose.yml`, `compose.yaml`, `*.tf`, `Chart.yaml` | Platform family only |
| VCS | `.git/HEAD`, `.git/config` | Branch bucket + remote host bucket only |
| Layout | top-level dirs, `turbo.json`, `nx.json`, `pnpm-workspace.yaml` | Monorepo patterns |
| README | `README.md` first 40 non-empty lines | Stack nouns only, max 20 tokens |

**Denied:** `.env*`, SSH keys, cloud credentials, editor secrets, arbitrary source files, test output, binaries, anything outside declared root, full git history/branch names.

#### 12. Observability

**Concrete `FileRetrievalLogger`** implementing existing `RetrievalLogger` ABC:

```python
class FileRetrievalLogger(RetrievalLogger):
    """JSONL file logger for retrieval events. Extends existing ABC."""

    def __init__(self, log_path: Path): ...

    async def log_retrieval(self, context, results, latency_ms):
        # Write RankingEvent as JSONL line

    async def log_retrieval_miss(self, tool_name, context):
        # Tool described via routing tool — negative signal for scorer

    async def log_tool_sequence(self, session_id, tool_a, tool_b):
        # Co-occurrence for future graph construction
```

**Required alerts:**
- Routing describe rate >10% over baseline for 30min
- Fallback Tier 5-6 >5% of sessions
- Scorer p95 >75ms for 15min
- Re-score frequency >1/5s sustained for 10min

#### 13. Migration

Feature flags in `RetrievalConfig`:

```python
enabled: bool = False        # Master kill switch (existing)
shadow_mode: bool = False    # Compute rankings, log, don't change exposure
scorer: str = "bmxf"        # "bmxf" | "keyword" | "passthrough"
```

**Rollout stages:** Shadow → Canary 10% → Canary 50% → GA 100% → Retire old path

**Cutover gates:** Recall@15 ≥5% improvement, describe rate ≥20% drop, p95 <50ms, Tier 5-6 <5%

**Rollback triggers:** p95 >75ms, describe rate +10%, any trust-boundary violation

### Phasing (MVP → Full)

#### Phase 0: Foundations (1-2 weeks)

- Copy `BMXIndex` → `bmx_index.py`, add field-weighted wrapper (no BM25+ delta needed — BMX subsumes it)
- `ToolDoc`, `ToolCatalogSnapshot` in `models.py`
- `catalog.py` with `build_snapshot()`
- `BMXFRetriever` implementing `ToolRetriever` with `rebuild_index(registry)`
- Wire pipeline into `MCPProxyServer.retrieval_pipeline` in `multi_mcp.py`
- Shadow mode flag
- Tests: `test_bmx_retriever.py`, `test_catalog_snapshot.py`
- **Exit:** BMXF scores in shadow. Existing behavior unchanged. All existing tests pass.

#### Phase 1: Safe Lexical MVP (2-3 weeks)

- `telemetry/scanner.py` with allowlisted root scanning
- `telemetry/evidence.py`, `telemetry/tokens.py`
- Environment-only ranking at session init
- Static category defaults (Tier 4)
- Bounded fallback ladder through Tier 6
- `routing_tool.py` registered in `_register_request_handlers()`
- `FileRetrievalLogger`
- Tests: `test_telemetry_scanner.py`, `test_routing_tool.py`
- **Exit:** Bounded turn-zero active set from roots. No full-catalog exposure. Recall@15 > baseline.

#### Phase 2: Turn-by-Turn Adaptive (2-3 weeks)

- Conversation query extraction
- `fusion.py` with weighted RRF and alpha-decay
- Dynamic K (base 15, max 20)
- Promote/demote hysteresis in `session.py`
- `SessionRoutingState`
- `telemetry/monitor.py` with change detection and adaptive polling
- `RankingEvent` structured logging
- Tests: `test_rrf_fusion.py`, `test_session_promote_demote.py`
- **Exit:** Describe rate improves over Phase 1. Churn bounded. p95 <50ms.

#### Phase 3: Rollout Hardening (1-2 weeks)

- Canary controls
- Dashboards and alerts
- Replay regression gates
- **Exit:** All rollout gates pass in shadow. Alerting complete.

#### Phase 4: Post-GA Learning (ongoing)

- PPMI token reweighting from usage logs
- Optional exploration injection behind flag
- Co-occurrence graph
- Neural reranker spike if tool count > 500

### Trade-Off Costs

| Decision | Gain | Cost |
|----------|------|------|
| BMX over existing TF-IDF as primary | Better length norm (restructured denominator), entropy-weighted query coverage, self-tuning params, sigmoid TF saturation, +1.15 nDCG@10 over BM25 on BEIR | Must copy `bmx.py`; `KeywordRetriever` already works |
| BMXF field weighting (5 sub-indexes) | 5-10% accuracy on name/namespace matches | More memory (~1MB for 500 tools), rebuild time |
| Static heuristic token weights | Ships immediately; no training data | Sub-optimal until PPMI in Phase 4 |
| CPU-only, no neural retrieval | Simple deploy; deterministic; <10ms scoring | Misses semantic matches |
| Conservative K (15-20) | Lean context window | May miss tools; routing tool is safety net |
| `retrieval_aliases` over embeddings | Cheap vocabulary mismatch reduction | Curated synonym maintenance |
| Routing tool for demoted tools | All 168 tools discoverable | Extra tool in schema; model learning curve |
| Telemetry restricted to roots | Strong privacy; spec-correct | Loses process/env-var signals |
| Promote/demote hysteresis | Prevents churn | Slower to reflect legitimate changes |
| Six-stage fallback | Never exposes all 168 | More code paths to test |
| Shadow rollout mandatory | Safe migration | Slower cutover |

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| BMX returns wrong tools consistently | Medium | High | Routing tool safety net; describe-as-negative-signal; alert on describe >10% |
| Stale env signal after context switch | Medium | Medium | Adaptive polling + roots/list_changed; force re-scan on routing proxy spike |
| Polyglot monorepo dilutes signals | Medium | Medium | Dynamic K +3; per-workspace scoring for turbo/nx projects |
| Large repo scan exceeds budget | Low | High | Depth 6, 10K cap, 150ms hard; partial evidence mode |
| Static weights poorly calibrated | Medium-Low | Medium | Ship with logging; PPMI at Phase 4 with >50 sessions |
| `mcp` package roots API unavailable | Low | High | Wrap raw JSON-RPC; graceful fallback to Tier 5 |

---

## Self-Evaluation

### Scored Against Same Criteria

| # | Criterion (Weight) | Best Input (E) | **This Synthesis** |
|---|-------------------|:---:|:---:|
| 1 | Spec Correctness (16%) | 5 | **5** |
| 2 | Cold Start (16%) | 5 | **5** |
| 3 | Scoring Quality (14%) | 5 | **5** |
| 4 | Implementability (14%) | 4 | **5** |
| 5 | Fallback Robustness (10%) | 5 | **5** |
| 6 | Simplicity/MVP (8%) | 4 | **4** |
| 7 | Observability (8%) | 5 | **5** |
| 8 | Security/Privacy (6%) | 4 | **5** |
| 9 | Extensibility (4%) | 4 | **5** |
| 10 | Migration Safety (4%) | 5 | **5** |
| | **Weighted Total** | 4.68 | **4.92** |

Synthesis total: (5×.16)+(5×.16)+(5×.14)+(5×.14)+(5×.10)+(4×.08)+(5×.08)+(5×.06)+(5×.04)+(5×.04) = .80+.80+.70+.70+.50+.32+.40+.30+.20+.20 = **4.92**

### Why This Plan Scores Higher

This synthesis improves on Plan E by grounding every component in the actual codebase:

- Maps `BMXIndex` from `bmx.py` to specific adaptation requirements (BMXF field weighting, `ToolMapping` adapter layer) — no BM25+ δ hack needed since BMX's restructured length normalization and entropy weighting subsume BM25+'s short-document fix
- Names exact files, classes, methods, and integration points in `src/multimcp/retrieval/`
- References existing patterns (`rebuild_index(registry)`, `_make_key()/_split_key()`, `ToolRetriever` ABC) that new code must follow
- Identifies the `TYPE_CHECKING`-guarded import and `Optional[RetrievalPipeline] = None` as the specific wiring point in `mcp_proxy.py`
- Specifies tests parallel to existing naming (`test_bmx_retriever.py` alongside `test_keyword_retriever.py`)
- Documents exact BMXIndex interface (`build_index(chunks)` with `{"chunk_id", "text"}`) and required transform to `ToolDoc` fields
- Upgrades the scoring engine from BM25/BM25+ to BMX, gaining ~+1.15 nDCG@10 on BEIR benchmarks at zero additional computational cost

### Top 3 Risks and Mitigations

1. **Lexical ranking misses semantically phrased conversation intent.** BMX cannot bridge "CI pipeline" → "continuous integration workflow." Mitigation: `retrieval_aliases` with curated synonym maps in Phase 1; neural reranker deferred to Phase 4.

2. **The `mcp` Python package may not expose roots API cleanly.** The spec defines roots but the SDK may require raw JSON-RPC wrapping. Mitigation: abstract behind `telemetry/scanner.py`; fall to Tier 5 if roots unavailable.

3. **BMXF field-weighted scoring adds complexity over single-index BMX.** Five sub-indexes per field increases memory and rebuild time. Mitigation: for 168-500 tools, memory is <1MB; rebuild <10ms. BMX's self-tuning parameters mean each sub-index auto-calibrates to its field's document length distribution — no per-field parameter tuning required. Validated by `BMXIndex.get_index_stats()`.

### Bias Check

- **Did I favor one input plan?** Yes — Plan E contributed the most architecture. Justified: it already performed the best cross-plan synthesis. This plan hardens it with code-level specificity rather than replacing it.
- **Does the synthesis survive its own weaknesses?** The vocabulary mismatch weakness persists but is managed via `retrieval_aliases` + synonym maps + Phase 4 neural path. Static weight calibration managed via logging from day 1 + PPMI.
- **Would a different timeline change this plan?** With 1-week sprint: skip telemetry, wire BMXF + routing tool only. With 3-month sprint + ML resources: Phase 4 neural reranker moves to Phase 2.
- **Did I add complexity without acknowledging cost?** BMXF field weighting (5 sub-indexes) adds memory and rebuild time. Cost acknowledged in trade-off table. Justified by 5-10% accuracy on name/namespace matches for a corpus where tool names are the strongest signal. BMX itself adds entropy precomputation at index-build time, but this is O(total postings) and amortized across queries — search-time cost is comparable to BM25.
