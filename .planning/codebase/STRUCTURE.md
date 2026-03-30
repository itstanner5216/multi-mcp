# Codebase Structure

**Analysis Date:** 2025-07-10

## Directory Layout

```
multi-mcp/
├── main.py                          # CLI entry point (start/status/list/refresh)
├── pyproject.toml                   # Python project metadata + dependencies
├── requirements.txt                 # Pinned requirements
├── uv.lock                          # uv lockfile
├── Makefile                         # Dev shortcuts (make run, make test-proxy, etc.)
├── Dockerfile                       # Production image (Python 3.12 + Node.js 20)
├── start-server.sh                  # Docker entrypoint
├── bmx_plus.py                      # Standalone BMX algorithm reference/prototype
├── llama-stack.py                   # LlamaStack integration prototype
│
├── src/
│   ├── multimcp/                    # Core proxy package
│   │   ├── multi_mcp.py             # Orchestrator, MCPSettings, HTTP API, transport startup
│   │   ├── mcp_proxy.py             # MCPProxyServer — core proxy, namespacing, tool routing
│   │   ├── mcp_client.py            # MCPClientManager — lifecycle, lazy connect, SSRF guard
│   │   ├── mcp_trigger_manager.py   # Keyword-triggered server auto-activation
│   │   ├── yaml_config.py           # YAML config schema (Pydantic), load/save
│   │   ├── cache_manager.py         # Tool cache merge/staleness logic
│   │   ├── cli.py                   # CLI sub-commands: status, list, refresh
│   │   ├── __init__.py
│   │   │
│   │   ├── retrieval/               # BMXF tool retrieval pipeline (Phase 7)
│   │   │   ├── pipeline.py          # RetrievalPipeline — entry point, 6-tier fallback ladder
│   │   │   ├── models.py            # RetrievalConfig, ScoredTool, ToolDoc, WorkspaceEvidence, etc.
│   │   │   ├── base.py              # ToolRetriever ABC
│   │   │   ├── bmx_retriever.py     # BMXFRetriever — field-weighted BMX, alias generation
│   │   │   ├── bmx_index.py         # BMXIndex — entropy-weighted BM25 successor implementation
│   │   │   ├── catalog.py           # build_snapshot() — canonical ToolCatalogSnapshot builder
│   │   │   ├── fusion.py            # weighted_rrf(), compute_alpha() — RRF blend + alpha decay
│   │   │   ├── session.py           # SessionStateManager — per-session active tool sets
│   │   │   ├── assembler.py         # TieredAssembler — full/summary tier assignment
│   │   │   ├── ranker.py            # RelevanceRanker — optional re-ranker
│   │   │   ├── keyword.py           # Fallback keyword retriever (Tier 3)
│   │   │   ├── namespace_filter.py  # Namespace-based pre-filter
│   │   │   ├── routing_tool.py      # Synthetic request_tool schema builder
│   │   │   ├── static_categories.py # STATIC_CATEGORIES per project type, TIER6_NAMESPACE_PRIORITY
│   │   │   ├── logging.py           # RetrievalLogger, NullLogger, FileRetrievalLogger
│   │   │   ├── metrics.py           # Retrieval latency / quality metrics
│   │   │   ├── rollout.py           # get_session_group() — canary/GA routing
│   │   │   ├── replay.py            # ReplayEvaluator — offline evaluation harness
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   └── telemetry/           # Workspace roots scanner
│   │   │       ├── scanner.py       # TelemetryScanner — filesystem scan of MCP roots
│   │   │       ├── evidence.py      # RootEvidence, WorkspaceEvidence, merge_evidence()
│   │   │       ├── tokens.py        # build_tokens() — manifest/lang/infra token builders
│   │   │       ├── monitor.py       # Background telemetry monitor
│   │   │       └── __init__.py
│   │   │
│   │   ├── adapters/                # Tool-host config generators
│   │   │   ├── base.py              # AdapterBase ABC
│   │   │   ├── registry.py          # AdapterRegistry — maps host names to adapters
│   │   │   ├── _toml_helpers.py     # TOML config utilities
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   └── tools/               # One adapter per IDE / AI tool host
│   │   │       ├── claude_desktop.py
│   │   │       ├── github_copilot.py
│   │   │       ├── cursor.py        # (via Cursor's mcp.json format)
│   │   │       ├── cline.py
│   │   │       ├── continue_dev.py
│   │   │       ├── codex_cli.py
│   │   │       ├── codex_desktop.py
│   │   │       ├── gemini_cli.py
│   │   │       ├── gptme.py
│   │   │       ├── jetbrains.py
│   │   │       ├── opencode.py
│   │   │       ├── openclaw.py
│   │   │       ├── raycast.py
│   │   │       ├── roo_code.py
│   │   │       ├── warp.py
│   │   │       ├── zed.py
│   │   │       ├── antigravity.py   # Generic/fallback adapter
│   │   │       └── __init__.py
│   │   │
│   │   └── utils/
│   │       ├── audit.py             # AuditLogger — tool call/failure audit trail
│   │       ├── config.py            # Config utilities
│   │       ├── keyword_matcher.py   # extract_keywords_from_message(), match_triggers()
│   │       └── __init__.py
│   │
│   └── utils/
│       └── logger.py                # configure_logging(), get_logger() — loguru wrapper
│
├── tests/                           # Comprehensive pytest test suite (~80 test files)
│   ├── proxy_test.py                # Core proxy functionality
│   ├── e2e_test.py                  # End-to-end integration
│   ├── lifecycle_test.py            # Client lifecycle management
│   ├── k8s_test.py                  # removed — Kubernetes deployment tests deferred
│   ├── test_retrieval_pipeline.py   # RetrievalPipeline unit tests
│   ├── test_bmx_retriever.py        # BMXFRetriever unit tests
│   ├── test_fallback_ladder.py      # 6-tier fallback behavior
│   ├── test_rrf_fusion.py           # RRF fusion + alpha decay
│   ├── test_telemetry_scanner.py    # Workspace scanner
│   ├── test_routing_tool.py         # Synthetic routing_tool schema
│   ├── test_security_validation.py  # SSRF + command allowlist
│   ├── utils.py                     # Shared test helpers and mock factories
│   ├── BM25-Tests/                  # BMX algorithm correctness tests
│   └── tools/                       # Test MCP server implementations
│
├── examples/
│   ├── config/                      # Sample mcp.json configurations
│   │   ├── mcp_basic.json
│   │   ├── mcp_k8s.json
│   │   └── ...
│   ├── k8s/                         # Kubernetes manifests
│   └── connect_langgraph_client.py  # LangGraph integration example
│
├── msc/
│   ├── mcp.json.bak                 # Production MCP config backup
│   └── README.md
│
├── docs/
│   ├── OPERATOR-RUNBOOK.md          # Deployment and operations guide
│   ├── TODO.md                      # Known work items
│   ├── PHASE2-SYNTHESIZED-PLAN.md   # Phase 7 BMXF design spec
│   └── implementation-audit-final.md
│
├── claude/                          # Investigation/session artifacts (Claude Code)
│   └── {timestamp}/                 # e.g. 250627114051/
│
├── .planning/                       # GSD planning workspace
│   ├── codebase/                    # Codebase analysis documents (this dir)
│   └── phases/                      # Phase implementation plans
│
└── assets/
    └── multi-mcp-diagram.png        # Architecture diagram
```

---

## Directory Purposes

**`src/multimcp/` (core package):**
- Purpose: All production code for the proxy server
- Contains: Orchestrator, proxy, client manager, retrieval pipeline, adapters, utilities
- Key files: `multi_mcp.py`, `mcp_proxy.py`, `mcp_client.py`, `yaml_config.py`

**`src/multimcp/retrieval/` (retrieval pipeline):**
- Purpose: Context-aware tool filtering — BMXF scoring, session state, workspace telemetry
- Contains: Pipeline entry point, BMX index, fusion logic, tiered fallback, routing tool
- Key files: `pipeline.py`, `bmx_retriever.py`, `bmx_index.py`, `fusion.py`, `models.py`
- Key files: `session.py`, `routing_tool.py`, `static_categories.py`

**`src/multimcp/retrieval/telemetry/` (workspace scanner):**
- Purpose: Scan MCP roots to produce workspace evidence tokens for retrieval scoring
- Contains: `TelemetryScanner`, `RootEvidence`, `WorkspaceEvidence`, token builders
- Key files: `scanner.py`, `evidence.py`, `tokens.py`

**`src/multimcp/adapters/` (host adapters):**
- Purpose: Generate MCP client config files for different IDE/AI tool hosts
- Contains: One module per supported tool (Claude Desktop, Cursor, VS Code, Zed, etc.)
- Key files: `base.py`, `registry.py`, `tools/*.py`

**`src/multimcp/utils/` (internal utilities):**
- Purpose: Audit logging, keyword trigger matching, config helpers
- Key files: `audit.py`, `keyword_matcher.py`

**`src/utils/` (shared utilities):**
- Purpose: Cross-package utilities
- Key files: `logger.py` — single `configure_logging()` / `get_logger()` API

**`tests/` (~80 test files):**
- Purpose: Unit, integration, E2E, K8s tests
- Pattern: pytest with `pytest-asyncio`; mock MCP servers in `tests/tools/`
- Shared helpers: `tests/utils.py`

**`examples/config/`:**
- Purpose: Sample `mcp.json` files for different deployment scenarios
- Use: Pass to `main.py start --config ./examples/config/mcp_k8s.json`

**`msc/`:**
- Purpose: Production MCP server config used in Docker deployment
- Key file: `mcp.json.bak` (GitHub, Brave Search, Context7 servers)

**`docs/`:**
- Purpose: Design docs, runbooks, TODO, implementation audits
- Key files: `OPERATOR-RUNBOOK.md`, `PHASE2-SYNTHESIZED-PLAN.md`

**`claude/`:**
- Purpose: Investigation artifacts from Claude Code sessions (per CLAUDE.md convention)
- Pattern: `claude/{timestamp}/` subdirectory per investigation

**`.planning/`:**
- Purpose: GSD workflow planning artifacts (phases, codebase docs, project state)
- Generated: Yes (managed by GSD commands)
- Committed: Yes

---

## Key File Locations

**Entry Points:**
- `main.py`: CLI interface; `start` / `status` / `list` / `refresh` sub-commands
- `src/multimcp/cli.py`: Non-server sub-commands (`cmd_status`, `cmd_list`, `cmd_refresh`)

**Configuration:**
- `src/multimcp/yaml_config.py`: `MultiMCPConfig`, `ServerConfig`, `ToolEntry` Pydantic models; `load_config()` / `save_config()`
- `src/multimcp/cache_manager.py`: `merge_discovered_tools()`, `get_enabled_tools()`
- Runtime YAML: `~/.config/multi-mcp/servers.yaml` (not in repo)

**Core Proxy:**
- `src/multimcp/mcp_proxy.py`: `MCPProxyServer`, `ToolMapping`, `_make_key()`, `_split_key()`, `_call_tool()`, `_list_tools()`, `toggle_tool()`, `register_client()`, `unregister_client()`
- `src/multimcp/mcp_client.py`: `MCPClientManager`, `get_or_create_client()`, `discover_all()`, `add_pending_server()`

**Retrieval:**
- `src/multimcp/retrieval/pipeline.py`: `RetrievalPipeline`, `get_tools_for_list()`, `on_tool_called()`, `set_session_roots()`
- `src/multimcp/retrieval/models.py`: All retrieval data types (`RetrievalConfig`, `ScoredTool`, `ToolDoc`, `WorkspaceEvidence`, etc.)
- `src/multimcp/retrieval/bmx_retriever.py`: `BMXFRetriever`, alias generation, field-weighted scoring
- `src/multimcp/retrieval/bmx_index.py`: `BMXIndex` — full BMX algorithm implementation
- `src/multimcp/retrieval/fusion.py`: `weighted_rrf()`, `compute_alpha()`
- `src/multimcp/retrieval/routing_tool.py`: `build_routing_tool_schema()`, `handle_routing_call()`, `ROUTING_TOOL_NAME`
- `src/multimcp/retrieval/static_categories.py`: `STATIC_CATEGORIES`, `TIER6_NAMESPACE_PRIORITY`
- `src/multimcp/retrieval/telemetry/scanner.py`: `TelemetryScanner.scan_roots()`

**Utilities:**
- `src/utils/logger.py`: `configure_logging(level)`, `get_logger(name)` (loguru-based)
- `src/multimcp/utils/audit.py`: `AuditLogger.log_tool_call()`, `log_tool_failure()`
- `src/multimcp/mcp_trigger_manager.py`: `MCPTriggerManager.check_and_enable()`

**Testing:**
- `tests/utils.py`: Mock server helpers, test fixtures
- `tests/tools/`: Minimal MCP server implementations for integration tests

---

## Naming Conventions

**Files:**
- Snake_case modules: `mcp_proxy.py`, `yaml_config.py`, `bmx_retriever.py`
- Test files: `test_<module_or_feature>.py` or legacy `<name>_test.py`
- Config files: `mcp.json` (tool-host format), `servers.yaml` (multi-mcp YAML format)

**Classes:**
- PascalCase: `MCPProxyServer`, `MCPClientManager`, `MultiMCP`, `BMXFRetriever`, `RetrievalPipeline`

**Functions:**
- Snake_case: `get_or_create_client()`, `merge_discovered_tools()`, `compute_alpha()`
- Private methods prefixed `_`: `_call_tool()`, `_list_tools()`, `_make_key()`
- Async functions: majority of proxy/client operations are `async def`

**Constants:**
- UPPER_SNAKE: `ROUTING_TOOL_NAME`, `PROTECTED_ENV_VARS`, `MAX_DEPTH`, `STATIC_CATEGORIES`

**Namespaced keys:**
- Tool keys: `server_name__tool_name` (double underscore `__` separator)
- Example: `github__search_repositories`, `brave-search__brave_web_search`

---

## Where to Add New Code

**New backend MCP server support:**
- No code needed — config-driven via `servers.yaml` or `mcp.json`
- Test with: `main.py refresh` to discover tools

**New retrieval tier (beyond Tier 6):**
- Add method `_tier7_*()` in `src/multimcp/retrieval/pipeline.py`
- Insert before Tier 6 block in `get_tools_for_list()`
- Add tests in `tests/test_fallback_ladder.py`

**New telemetry token type (workspace signal):**
- Add to `MANIFEST_LANGUAGE_MAP` or new section in `src/multimcp/retrieval/telemetry/tokens.py`
- Scanner in `src/multimcp/retrieval/telemetry/scanner.py` picks it up automatically

**New static project category:**
- Add entry to `STATIC_CATEGORIES` dict in `src/multimcp/retrieval/static_categories.py`
- Update `_classify_project_type()` in `pipeline.py` if new signals needed

**New HTTP API endpoint:**
- Add `Route(...)` in `MultiMCP.create_starlette_app()` (`src/multimcp/multi_mcp.py`)
- Add handler method `handle_<name>()` on `MultiMCP`
- Wrap with `self._auth_wrapper()` for auth-protected routes

**New tool-host adapter:**
- Create `src/multimcp/adapters/tools/<host_name>.py` extending `AdapterBase`
- Register in `src/multimcp/adapters/registry.py`

**New utility (cross-cutting):**
- Shared across packages: `src/utils/`
- Internal to multimcp: `src/multimcp/utils/`

**New tests:**
- Unit tests for retrieval: `tests/test_<module>.py`
- Integration test: `tests/e2e_test.py` or new `tests/test_<feature>.py`
- Mock servers used in integration tests: `tests/tools/`
- Shared fixtures/helpers: `tests/utils.py`

---

## Special Directories

**`~/.config/multi-mcp/` (runtime, not in repo):**
- Purpose: Persistent YAML config (`servers.yaml`) written on first run
- Generated: Yes, by `MultiMCP._bootstrap_from_yaml()`
- Committed: No

**`.planning/`:**
- Purpose: GSD workflow artifacts — project state, phase plans, codebase docs
- Generated: Yes, by GSD commands
- Committed: Yes (tracks planning history)

**`claude/`:**
- Purpose: Claude Code investigation notes, stored per-session timestamp
- Convention: `claude/{YYMMDDHHMMSS}/` per CLAUDE.md
- Committed: Yes (investigation history)

**`tests/BM25-Tests/`:**
- Purpose: Correctness tests for the BMX scoring algorithm
- Generated: No (authored tests)
- Committed: Yes

**`logs/` (runtime, may be empty):**
- Purpose: Server log output directory
- Generated: Yes, at runtime
- Committed: No (empty dir placeholder)

---

*Structure analysis: 2025-07-10*
