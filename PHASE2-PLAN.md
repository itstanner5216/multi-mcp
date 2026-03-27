# Multi-MCP Phase 2: Intelligent Tool Routing & Cold Start

## Problem Statement

Multi-MCP currently exposes all 168 tools on session start because the top-K retrieval pipeline has no context to score against at turn zero. OpenAI API models immediately fail. The retrieval pipeline exists (TF-IDF keyword scoring, relevance ranker, tiered assembler, monotonic session state) but is hardcoded to disabled. Beyond fixing the cold start, the goal is to build a system where tools are never removed from the model's view — only promoted (fully exposed) or demoted (collapsed into a routing tool as bare names).

## Architecture Overview

### The Core Loop
1. Session starts → roots telemetry reads environment before first turn
2. Scoring engine (embeddings primary, TF-IDF fallback) selects top-K tools
3. Top-K tools fully exposed with schema + description
4. Remaining tools collapsed into routing tool as bare names (no descriptions, no schemas)
5. Model works — if it needs a collapsed tool, it calls the routing tool by name
6. Context shifts → telemetry + conversation signal re-scores → different tools promoted/demoted
7. **Nothing is ever removed** — tools only move between "fully exposed" and "collapsed in router"

### Key Principles
- No tool is ever subtracted from the model's view — only redacted (collapsed)
- Routing tool holds all demoted tool names so the model knows they exist
- Embeddings are the primary scorer; TF-IDF (already built) is the fallback
- Roots telemetry provides pre-turn-one context for cold start
- System degrades gracefully: embeddings → TF-IDF → passthrough

---

## Components to Build

### 1. Wire Existing Retrieval Pipeline
- Fix the hardcoded `RetrievalConfig(enabled=False)` in `multi_mcp.py` (~line 476)
- Pass through YAML `retrieval` config to the pipeline
- Fix session ID extraction (currently hardcoded to `"default"`)
- This alone gets top-K working with TF-IDF scoring

### 2. Routing Tool (Collapse/Expand Mechanism)
- New MCP tool exposed to the model: something like `use_tool` or `request_tool`
- Holds a registry of all demoted tool names (no descriptions, no schemas)
- Model can call it two ways:
  - `request_tool(name="github__search_repos")` → proxies the call through to the actual tool
  - `request_tool(name="github__search_repos", describe=true)` → returns the full description so the model can remember what it does
- When a tool is demoted from top-K, it moves into the routing tool's name registry
- When a tool is promoted back to top-K, it leaves the routing tool registry and becomes fully exposed
- The routing tool's schema dynamically updates its enum of available names

### 3. Embedding Retriever
- New retriever class alongside `KeywordRetriever`, implementing the existing `ToolRetriever` abstract base
- Embeds tool descriptions at registration time, stores vectors in a local DB (SQLite)
- Multi-variant descriptions per tool:
  - On registration: LLM generates 4-5 variant descriptions of each tool
  - At runtime: capture the context that led to successful tool calls
  - Feed real context snippets back as additional description variants over time
- Per-turn: embed current context (conversation + telemetry), cosine similarity against stored tool vectors, return top-K
- Primary embedding backend: **Google Vertex AI Vector Search** ($1000 in credits available)
  - Use Vertex AI embeddings API for generating vectors (e.g., `text-embedding-005`)
  - Use Vertex AI Vector Search for similarity matching (managed index, fast ANN lookup)
  - Handles both tool description embedding and per-turn context embedding
  - No local model overhead, no self-managed vector DB
- Fallback for when Vertex AI is unavailable or credits exhausted:
  - TF-IDF keyword retriever (already built) — zero cost, runs anywhere
  - Optional: local sentence-transformers as a middle tier if user has GPU

### 4. Roots Telemetry Integration
- Read MCP roots at session initialization (before first turn)
- Extract environmental signals: cwd, file types present, project structure, running processes, git state
- Feed this as initial context to the scoring engine
- This solves cold start: environment exists before conversation does
- Continue reading roots throughout session for context shifts

### 5. Cold Start Strategy
- Priority order for turn-zero tool selection:
  1. Roots telemetry → score tools against environment signal
  2. Per-user frequency data → "tools this user calls first most often" (phase 2, requires usage logging)
  3. Global frequency defaults → hardcoded list of universally common first-turn tools (developer sets this from their own usage data as initial seed)
- Any of these produces a reasonable top-K without conversation context

### 6. Fallback Chain
- Scoring: Embeddings → TF-IDF (existing `KeywordRetriever`) → Passthrough (expose all)
- Each level activates automatically when the higher level is unavailable or fails
- User can force a level via YAML config (e.g., `retrieval.scorer: keyword` to skip embeddings entirely)
- Fallback is per-request, not per-session — if embeddings fail mid-session, that request falls back to TF-IDF, next request tries embeddings again

### 7. Usage Logging (for adaptive cold start)
- Log every tool call: timestamp, tool name, session context summary, turn number
- Aggregate into frequency tables per-user
- Use frequency data to seed cold start when roots telemetry is insufficient
- This data also feeds back into embedding quality — real usage patterns > synthetic descriptions

---

## What Already Exists (Don't Rebuild)
- TF-IDF `KeywordRetriever` with tokenization, IDF scoring, namespace boost → **this is the fallback scorer**
- `RelevanceRanker` with specificity tiebreaking and primacy bias → **reuse for all scorers**
- `TieredAssembler` with full/summary description tiers → **reuse, extend for routing tool tier**
- `SessionStateManager` with monotonic expansion guarantee → **reuse, extend for routing tool state**
- `ToolRetriever` abstract base class → **implement `EmbeddingRetriever` from this**
- YAML config with per-tool enable/disable → **extend with embedding metadata**
- `cache_manager.py` merge logic (never delete) → **already handles the philosophy**
- Audit logging with JSONL → **extend for usage logging**

---

## Suggested Worktree Split (3 agents)

### Worktree A: Routing Tool + Wiring
- Wire existing retrieval pipeline (fix hardcoded disabled)
- Build the routing tool (collapse/expand mechanism)
- Modify `_list_tools()` to return top-K fully exposed + routing tool with demoted names
- Modify `_call_tool()` to handle routing tool proxy calls
- Session ID extraction fix

**Files owned:** `mcp_proxy.py`, new `routing_tool.py`, `retrieval/assembler.py` (extend for routing tier)

### Worktree B: Embedding Retriever + Storage
- New `EmbeddingRetriever` class implementing `ToolRetriever`
- **Google Vertex AI** integration:
  - Vertex AI Embeddings API for vectorizing tool descriptions and context (e.g., `text-embedding-005`)
  - Client abstraction so the Vertex dependency is swappable
- **`sqlite-vec`** for local vector storage and KNN search
  - `vec0` virtual table, native SQL KNN queries
  - Populated by Vertex AI, queried locally with zero network dependency
- Vector storage strategy:
  - **`sqlite-vec`** extension for local vector storage and KNN search (`pip install sqlite-vec`)
  - `vec0` virtual table stores tool description embeddings with native KNN via `WHERE embedding MATCH ? ORDER BY distance LIMIT K`
  - Vertex AI Embeddings API generates the vectors → `sqlite-vec` stores and queries them locally forever
  - When credits expire: all vectors already cached in `sqlite-vec`, zero degradation — search is fully local
  - New tools after credits gone: TF-IDF scores them until credits are topped up, then batch-embed the gap
  - ~2.5 MB total storage for 840 vectors at 768 dimensions — trivial
  - Zero cold boot, zero network dependency for search — Vertex AI is only needed for vector generation, not retrieval
  - No Qdrant, no Neon, no external vector DB needed
- Multi-variant description generation at registration
- Runtime context capture and feedback loop
- Embedding backend abstraction (local/API/none)

**Files owned:** new `retrieval/embedding.py`, new `retrieval/vertex_client.py`, new `retrieval/vector_store.py` (sqlite-vec wrapper), new `retrieval/description_generator.py`, `yaml_config.py` (extend schema)

### Worktree C: Roots Telemetry + Cold Start + Fallback
- Roots telemetry reader
- Cold start scoring logic
- Fallback chain (embeddings → TF-IDF → passthrough)
- Usage logging infrastructure
- Integration into `multi_mcp.py` orchestration

**Files owned:** new `roots_telemetry.py`, new `retrieval/fallback.py`, new `usage_logger.py`, `multi_mcp.py` (orchestration changes), `retrieval/pipeline.py` (fallback wiring)

---

## Integration Points (Merge Coordination)
- Worktree A's routing tool needs Worktree B's embedding scores to decide what's top-K vs demoted → **interface agreed upfront, integrated at merge**
- Worktree C's fallback chain wraps both B's embedding retriever and the existing keyword retriever → **C depends on B's interface, not implementation**
- Worktree A's `_list_tools()` changes need Worktree C's cold start to feed initial scores → **A uses a scoring interface that C implements**
- All three need the `RetrievalConfig` schema extended → **agree on schema before splitting**

## Notes
- The existing 578 tests should not break — all new functionality is additive
- Each worktree should include tests for its components
- The retrieval pipeline's `enabled` flag becomes the master switch — when disabled, everything falls through to passthrough (current behavior preserved)
- $800 in 2 weeks means we should be efficient with agent calls — plan thoroughly, execute precisely, minimize re-work
