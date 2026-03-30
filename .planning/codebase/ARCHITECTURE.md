# Architecture

**Analysis Date:** 2025-07-10

## Pattern Overview

**Overall:** Transparent MCP Proxy with Context-Aware Tool Retrieval

Multi-MCP presents a single MCP server to the upstream client (an AI agent or tool host) while maintaining N live connections to downstream backend MCP servers. The proxy layer aggregates all tools/prompts/resources under a namespaced key scheme, then filters the visible tool list at each `tools/list` call through a BMXF retrieval pipeline that scores tools against workspace evidence and conversation context.

**Key Characteristics:**
- Single-server facade: one MCP endpoint, any number of backends
- Double-underscore namespace (`server__tool`) isolates backend identities
- Lazy connection model: servers are registered as pending; TCP/subprocess connections open on first tool call
- Progressive disclosure: up to K=20 direct tools exposed per session; remaining tools accessible via a synthetic `request_tool` routing entry
- Dual transport: STDIO for local agent use, SSE (HTTP) for networked access with optional Bearer auth

---

## Component Map

```
┌─────────────────────────────────────────────────────────────┐
│                        Upstream Client                       │
│              (Claude, LangChain, any MCP host)              │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP (STDIO or SSE)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                      MultiMCP  (Orchestrator)                │
│  src/multimcp/multi_mcp.py                                  │
│                                                              │
│  • Parses CLI args / MCPSettings (pydantic-settings)        │
│  • Bootstraps YAML config (~/.config/multi-mcp/servers.yaml)│
│  • Runs first-time discovery if no YAML exists              │
│  • Starts background tasks: idle-checker, always-on watchdog│
│  • Hosts Starlette HTTP routes (SSE mode only)              │
│  • HTTP API: GET/POST/DELETE /mcp_servers, GET /mcp_tools,  │
│             POST /mcp_control, GET /health                  │
└────────────────────────┬────────────────────────────────────┘
                         │ creates & wires
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCPProxyServer  (Core Proxy)              │
│  src/multimcp/mcp_proxy.py                                  │
│                                                              │
│  • Extends mcp.server.Server                                │
│  • Registers handlers: tools/list, tools/call,             │
│    prompts/list, get_prompt, resources/list, read_resource  │
│  • Maintains tool_to_server, prompt_to_server,             │
│    resource_to_server dicts (ToolMapping / etc. dataclasses)│
│  • _make_key() / _split_key(): "server__tool" namespacing  │
│  • toggle_tool(): per-tool runtime enable/disable          │
│  • circuit breaker: auto-quarantine after 3 failures       │
│  • Holds RetrievalPipeline reference (None = passthrough)  │
│  • Sends tools/list_changed on any structural change       │
└──────────┬──────────────────┬──────────────────────────────┘
           │                  │
           ▼                  ▼
┌──────────────────┐  ┌───────────────────────────────────────┐
│ MCPClientManager │  │          RetrievalPipeline             │
│ mcp_client.py    │  │  src/multimcp/retrieval/pipeline.py   │
│                  │  │                                        │
│ AsyncExitStack   │  │ • Tiered fallback scoring (Tiers 1-6) │
│ per-server       │  │ • Session state per connection         │
│ Lazy pending dict│  │ • BMXF env + conv RRF fusion          │
│ SSRF validation  │  │ • Workspace evidence integration      │
│ Command allowlist│  │ • K-bounded output (15–20 direct)     │
│ Idle eviction    │  │ • Synthetic routing_tool injection    │
│ Always-on watchdg│  │ • Progressive disclosure on_tool_call │
└──────────┬───────┘  └──────────┬────────────────────────────┘
           │                     │
    ┌──────┴────────┐    ┌───────┴─────────────────────┐
    │ N Backend MCP │    │       BMXFRetriever           │
    │ Servers       │    │ retrieval/bmx_retriever.py   │
    │               │    │                              │
    │ STDIO (subproc│    │ • BMXIndex: entropy-weighted │
    │ SSE  (HTTP)   │    │   BM25 successor (arXiv:2408)│
    │ StreamableHTTP│    │ • 5-field scoring:           │
    └───────────────┘    │   name/namespace/description │
                         │   parameters/aliases         │
                         │ • rebuild_index() on change  │
                         └──────────────────────────────┘
```

---

## Layers

**Orchestration Layer:**
- Purpose: Configuration, transport selection, HTTP API surface, background lifecycle
- Location: `src/multimcp/multi_mcp.py`
- Contains: `MultiMCP` class, `MCPSettings` (pydantic-settings with `MULTI_MCP_` prefix)
- Depends on: `MCPClientManager`, `MCPProxyServer`, `yaml_config`, `cache_manager`
- Used by: `main.py` entry point, Docker/K8s deployments

**Proxy Layer:**
- Purpose: MCP protocol handling, tool namespacing, capability aggregation, routing
- Location: `src/multimcp/mcp_proxy.py`
- Contains: `MCPProxyServer(server.Server)`, `ToolMapping`, `PromptMapping`, `ResourceMapping` dataclasses
- Depends on: `MCPClientManager`, `RetrievalPipeline`, `AuditLogger`, `MCPTriggerManager`
- Used by: `MultiMCP.run()` — instantiated once per server process

**Client Lifecycle Layer:**
- Purpose: Manage N backend connections (lazy/eager), SSRF protection, idle eviction
- Location: `src/multimcp/mcp_client.py`
- Contains: `MCPClientManager` class
- Key state: `clients` (connected), `pending_configs` (lazy, not yet connected), `server_stacks` (per-server `AsyncExitStack`), `tool_filters`, `idle_timeouts`
- Depends on: `mcp.client.stdio`, `mcp.client.sse`, `mcp.client.streamable_http`
- Used by: `MCPProxyServer`, `MultiMCP`

**Retrieval Layer:**
- Purpose: Context-aware tool ranking to bound the active tool list to K=15–20
- Location: `src/multimcp/retrieval/`
- Contains: `RetrievalPipeline`, `BMXFRetriever`, `BMXIndex`, `SessionStateManager`, models, fusion, routing_tool, telemetry scanners
- Depends on: no external ML libraries; pure Python with math/collections
- Used by: `MCPProxyServer._list_tools()`, `MCPProxyServer._call_tool()`

**Configuration Layer:**
- Purpose: YAML config persistence, tool cache, profile/filter management
- Location: `src/multimcp/yaml_config.py`, `src/multimcp/cache_manager.py`
- Contains: `MultiMCPConfig`, `ServerConfig`, `ToolEntry`, `ProfileConfig` Pydantic models; `merge_discovered_tools()`, `get_enabled_tools()`
- YAML written to: `~/.config/multi-mcp/servers.yaml`

**Adapter Layer:**
- Purpose: Per-tool-host config generators (writes MCP JSON for Claude Desktop, VSCode, Cursor, etc.)
- Location: `src/multimcp/adapters/`
- Contains: `src/multimcp/adapters/tools/` — one module per IDE/host, `AdapterBase`, `AdapterRegistry`

---

## Data Flow

**Session Startup (STDIO mode):**

1. `main.py` parses CLI → `MultiMCP(transport="stdio").run()`
2. `_bootstrap_from_yaml()` loads `~/.config/multi-mcp/servers.yaml`
   - If absent: `_first_run_discovery()` scans Claude plugins, Claude Desktop config, VSCode, Cursor, Windsurf, Zed, Copilot, OpenCode configs
   - Connects to each discovered backend, calls `list_tools()`, writes YAML
3. All servers registered as `pending_configs` in `MCPClientManager` (no connections yet)
4. `MCPProxyServer.create()` → `load_tools_from_yaml()` pre-populates `tool_to_server` with `client=None` stubs (tools visible immediately without connecting)
5. `RetrievalPipeline` constructed with `BMXFRetriever`; `rebuild_index()` called on stub tools
6. `always_on` servers connect in background task
7. `stdio_server()` context opens; `MCPProxyServer.run()` begins message loop
8. On session init: `_request_and_set_roots()` fires → retrieval pipeline stores `WorkspaceEvidence`

**Tool Call Flow:**

1. Upstream client sends `tools/call { name: "github__search_repositories", arguments: {...} }`
2. `MCPProxyServer._call_tool()` receives request
3. `MCPTriggerManager.check_and_enable()` scans message for keyword triggers (may connect pending servers)
4. `tool_to_server.get("github__search_repositories")` → `ToolMapping`
5. If `mapping.client is None` (lazy): `client_manager.get_or_create_client("github")` connects the subprocess; `initialize_single_client()` re-registers tools with live client
6. `_split_key("github__search_repositories")` → `("github", "search_repositories")`
7. `client.call_tool("search_repositories", arguments)` forwarded to backend
8. `audit_logger.log_tool_call()` records the call
9. `retrieval_pipeline.on_tool_called()` updates session tool history; may disclose new tools
10. If failure count ≥ 3: `toggle_tool(enabled=False)` auto-quarantines

**tools/list Flow (with retrieval pipeline):**

1. `MCPProxyServer._list_tools()` called at each `tools/list` request
2. Session context assembled: `get_session_tool_history()` + `get_session_argument_keys()` + `get_session_router_describes()`
3. `RetrievalPipeline.get_tools_for_list(session_id, conversation_context)` runs:
   - Advances turn counter
   - Builds `env_query` from `WorkspaceEvidence.merged_tokens` (roots telemetry)
   - Builds `conv_query` via `_extract_conv_terms()` (stopword removal, bigrams, action verb expansion)
   - Runs 6-tier fallback ladder (see Retrieval Pipeline section below)
4. Returns top `dynamic_k` tools + synthetic `request_tool` entry for demoted tools

**Dynamic Server Add (SSE mode):**

1. `POST /mcp_servers { "mcpServers": { "name": { ... } } }`
2. Auth check (`Authorization: Bearer <key>`)
3. `client_manager.add_pending_server()` registers config
4. Eager connect attempt: `create_clients()` → `register_client()` on proxy
5. `_send_tools_list_changed()` notifies upstream client
6. `retrieval_pipeline.rebuild_catalog()` rebuilds BMXF index with new tools

---

## STDIO vs SSE Transport Duality

Both transports run the same `MCPProxyServer` instance. The transport layer is a thin wrapper:

**STDIO (`transport="stdio"`):**
- Entry: `MultiMCP.start_stdio_server()` → `mcp.server.stdio.stdio_server()` context
- Streams: `read_stream` / `write_stream` from `stdio_server()`
- Profile applied globally (one session per process)
- No HTTP endpoints exposed

**SSE (`transport="sse"`):**
- Entry: `MultiMCP.start_sse_server()` → `uvicorn.Server(starlette_app).serve()`
- Routes: `/sse` (SSE stream), `/messages/` (POST message handler), REST API endpoints
- Per-session profile via `?profile=name` query param (tool filters saved/restored per request)
- `SseServerTransport.connect_sse()` creates streams; same `MCPProxyServer.run()` call as STDIO
- Auth: `Authorization: Bearer <key>` header (or deprecated `?token=` for `/sse`)
- Multiple concurrent SSE sessions supported (per-session tool filter copy pattern)

---

## Retrieval Pipeline — 6-Tier Fallback Ladder

Location: `src/multimcp/retrieval/pipeline.py`, `RetrievalPipeline.get_tools_for_list()`

**Dynamic K:** base 15, +3 if polyglot workspace (`lang:*` token count > 1), max 20

**Tier 1 — BMXF env+conv blend (normal operation, turn > 0):**
- Runs `BMXFRetriever.retrieve()` with env query AND conv query separately
- Fuses via `weighted_rrf(env_ranked, conv_ranked, alpha)` from `retrieval/fusion.py`
- `compute_alpha()` decays from 0.85 (env-dominated) at turn 0 to floor 0.15 at turn 10+; adjusts for workspace confidence and explicit tool mentions
- Requires: index built + both queries non-empty + turn > 0 + fusion module available

**Tier 2 — BMXF env-only:**
- `BMXFRetriever.retrieve()` with env query only
- Fallback when conv query empty or Tier 1 exception

**Tier 3 — KeywordRetriever env-only:**
- Fallback when BMXF unavailable (import error)

**Tier 4 — Static category defaults:**
- `_classify_project_type()` inspects `WorkspaceEvidence.merged_tokens` (manifest files, lang tokens)
- Matches to `STATIC_CATEGORIES` in `retrieval/static_categories.py` (infrastructure/rust_cli/python_web/node_web/generic)
- `always` tier tools score 1.0, `likely` tier score 0.8

**Tier 5 — Time-decayed frequency prior:**
- Reads JSONL from `FileRetrievalLogger`; 7-day window; `exp(-0.1 * days_ago)` decay

**Tier 6 — Universal 12-tool fallback:**
- `TIER6_NAMESPACE_PRIORITY` order from `static_categories.py`; fills remaining slots lexicographically

**Post-scoring:**
- Top `direct_k` sorted by score → active set
- Demoted tools injected into `build_routing_tool_schema(demoted_ids)` → synthetic `request_tool` appended
- `session_manager.set_active_tools()` persists active set; `on_tool_called()` triggers progressive disclosure

---

## Workspace Telemetry (Roots Scanning)

Location: `src/multimcp/retrieval/telemetry/scanner.py`, `evidence.py`, `tokens.py`

**Flow:**
1. After session init, `_request_and_set_roots()` calls `session.list_roots()` → `[{uri: "file:///workspace"}]`
2. `TelemetryScanner.scan_roots(root_uris)` walks filesystem (max depth 6, max 10K entries, 150ms timeout)
3. Allowlisted files only: manifests (package.json, pyproject.toml, Cargo.toml…), lockfiles, CI files, container files, infra files, DB schema files, README
4. Denied: `.env*`, `*.pem`, `*.key`, `id_rsa*`, credential files
5. `build_tokens()` produces weighted evidence tokens: `manifest:package.json`, `lang:python`, `infra:kubernetes`, etc.
6. `merge_evidence()` aggregates across multiple roots → `WorkspaceEvidence.merged_tokens`
7. Stored per-session in `RetrievalPipeline._session_evidence[session_id]`
8. On `roots/list_changed` notification: re-scan immediately

---

## Capability Aggregation

**Tools:** Namespaced as `server__tool_name`. Stored in `tool_to_server: dict[str, ToolMapping]`. Filter applied via `tool_filters[server_name] = {"allow": [...], "deny": [...]}`. YAML cache enables immediate listing before connections open.

**Prompts:** Namespaced as `server__prompt_name`. Stored in `prompt_to_server`. Served from cache; full content fetched on `get_prompt`.

**Resources:** Keyed by raw URI (not namespaced). Stored in `resource_to_server`. URI passed directly to backend on `read_resource`.

**Capability checks:** During `initialize_single_client()`, `result.capabilities.tools/prompts/resources` inspected before calling respective `list_*` methods — prevents "Method not found" errors from servers that don't implement all MCP methods.

---

## Key Abstractions

**ToolMapping (dataclass):**
- Purpose: Maps a namespaced tool key to its backend client and original tool definition
- Fields: `server_name: str`, `client: Optional[ClientSession]` (None = lazy pending), `tool: types.Tool`
- Location: `src/multimcp/mcp_proxy.py`

**MCPSettings (pydantic-settings):**
- Purpose: All runtime configuration with `MULTI_MCP_` env var prefix
- Fields: `host`, `port`, `transport`, `log_level`, `config`, `api_key`, `profile`
- Location: `src/multimcp/multi_mcp.py`

**MultiMCPConfig (Pydantic model):**
- Purpose: Persistent YAML config schema — servers, tool caches, profiles, sources
- Fields: `servers: dict[str, ServerConfig]`, `profiles`, `sources`, `exclude_servers`, `retrieval`
- Location: `src/multimcp/yaml_config.py`

**RetrievalConfig (dataclass):**
- Purpose: Pipeline feature flags and tuning knobs
- Key fields: `enabled`, `shadow_mode`, `rollout_stage` ("shadow"|"canary"|"ga"), `max_k`, `canary_percentage`
- Location: `src/multimcp/retrieval/models.py`

**ScoredTool (dataclass):**
- Purpose: Retrieval output unit — tool key + mapping + score + tier
- Location: `src/multimcp/retrieval/models.py`

---

## Entry Points

**`main.py` (primary):**
- Location: `main.py`
- Triggers: CLI (`uv run main.py start --transport stdio`)
- Responsibilities: Argument parsing, instantiates `MultiMCP`, calls `asyncio.run(server.run())`
- Sub-commands: `start`, `status`, `list`, `refresh`

**`MCPProxyServer.run()` (session loop):**
- Location: `src/multimcp/mcp_proxy.py` line ~871
- Triggers: `MultiMCP.start_stdio_server()` or per SSE connection
- Responsibilities: `ServerSession` lifecycle, roots request, message dispatch loop
- Note: Reimplements `server.Server.run()` to capture `_server_session` reference for notifications

**HTTP API (SSE mode only):**
- `GET /mcp_servers` — list active + pending servers
- `POST /mcp_servers` — add new backend servers at runtime
- `DELETE /mcp_servers/{name}` — remove a backend server
- `GET /mcp_tools` — list all tools grouped by server
- `POST /mcp_control` — toggle individual tools, trigger actions
- `GET /health` — health check

---

## Error Handling

**Strategy:** Log and continue per-server; never crash the proxy for one server's failure

**Patterns:**
- Backend connection failure at init: server removed from `clients`, continues without it
- Tool call exception: `isError=True` response returned to upstream; failure count incremented
- Circuit breaker: 3 consecutive transport exceptions → `toggle_tool(enabled=False)` auto-quarantine; re-enable via `POST /mcp_control`
- YAML parse error: returns `MultiMCPConfig()` (empty) and logs; proxy starts with no servers
- Roots/list not supported by client: swallowed as debug-level log (not an error)

---

## Cross-Cutting Concerns

**Logging:** `loguru`-based via `src/utils/logger.py`. Namespaced loggers (`multi_mcp.ProxyServer`, `multi_mcp.ClientManager`, etc.). Rich emoji prefixes: ✅ success, ❌ error, ⚠️ warning, 🔌 connection, 📢 notification.

**Audit Logging:** `src/multimcp/utils/audit.py` — `AuditLogger` records every `call_tool` invocation and failure to a separate audit trail.

**Security:** `mcp_client.py` enforces: command allowlist (`MULTI_MCP_ALLOWED_COMMANDS`), SSRF protection (private IP blocklist with async DNS resolution), protected env var list (no `LD_PRELOAD`, `PYTHONPATH`, etc. injection).

**Concurrency:** `asyncio` single-threaded. `AsyncExitStack` per server. `asyncio.Lock` (`_register_lock`) guards `tool_to_server` mutation. Per-server `_creation_locks` prevent concurrent lazy-connect races. `asyncio.Semaphore` caps concurrent connections at 10.

**Background Tasks:** Tracked in `MultiMCP._bg_tasks: set[asyncio.Task]`. Done callbacks log failures. All cancelled on graceful shutdown (`SIGTERM`/`SIGINT`).

---

*Architecture analysis: 2025-07-10*
