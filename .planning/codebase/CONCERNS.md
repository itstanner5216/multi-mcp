# Codebase Concerns

**Analysis Date:** 2026-03-29

---

## Tech Debt

### Phase 8 — Session ID Derivation is `id(object)`, Not a Real MCP Session ID

- **Issue:** `_get_session_id()` in `src/multimcp/mcp_proxy.py:348-356` returns `str(id(self._server_session))` — a CPython object identity integer — as the session key. This is a per-connection proxy, so in practice there is only one `_server_session` per proxy instance, making this largely functional in stdio mode. However, it is not a stable, transport-issued MCP session ID (which the protocol doesn't yet expose in the SDK API), and it falls back to the literal string `"default"` when no session is active (pre-initialization tool list calls).
- **Impact:** Any multi-session SSE scenario (multiple simultaneous SSE connections sharing one `MCPProxyServer` instance) would incorrectly merge session state. Session state in the retrieval pipeline (`_session_turns`, `_session_roots`, `_session_evidence`, `_session_tool_history`, `_session_arg_keys`, `_session_router_describes`) is keyed by this pseudo-ID. Currently acceptable because SSE multi-connection is not the primary use case and `_server_session` is per-proxy, but fragile if the architecture changes.
- **Files:** `src/multimcp/mcp_proxy.py:348-356`, `src/multimcp/retrieval/pipeline.py:164-171`
- **Fix approach:** When the MCP SDK exposes a real session ID in request context, replace `_get_session_id()` to extract it. In the interim, document the single-session limitation.

---

### `on_tool_called` Records Only; Promotion at `get_tools_for_list` — Fragile if Client Never Calls `tools/list`

- **Issue:** `pipeline.on_tool_called()` (`src/multimcp/retrieval/pipeline.py:718-746`) records the tool name to `_session_tool_history` but explicitly does NOT promote or advance the turn. Turn promotion happens in `get_tools_for_list()` (`pipeline.py:483-493`). This design is intentional (Issue 7 fix — batch promotion per turn boundary), but creates a behavioral gap: if a client calls tools via `tools/call` multiple times without ever calling `tools/list` again (e.g., long-running agentic loops that cache the tool list), no promotion or turn advance ever happens. The session's active set stays frozen and `_session_turns` never increments.
- **Impact:** Promotion-dependent signals (turn-based context, frequency tracking) silently fail for agentic clients that batch tool calls without re-listing. No error is raised.
- **Files:** `src/multimcp/retrieval/pipeline.py:483-493, 718-746`, `src/multimcp/mcp_proxy.py:389-406`
- **Fix approach:** Consider either (a) emitting a turn boundary in `on_tool_called` after N consecutive calls without a `list`, or (b) documenting this client behavior requirement explicitly.

---

### `demote()` is Implemented but Never Called — Active Tool Set Grows Monotonically

- **Issue:** `SessionStateManager.demote()` (`src/multimcp/retrieval/session.py:65`) is fully implemented and unit-tested, but is never called anywhere in `pipeline.py`, `mcp_proxy.py`, or `multi_mcp.py`. The session's active tool set only grows via `promote()`. Once a tool enters the active set it stays there for the session's lifetime. The "demote based on consecutive low rank" strategy from the design plan is not wired.
- **Impact:** Session active sets expand without bound during long sessions. Tools that were relevant earlier but are no longer needed remain pinned. In extreme cases this could undermine K-bounding.
- **Files:** `src/multimcp/retrieval/session.py:65-84`, `src/multimcp/retrieval/pipeline.py` (no call site)
- **Fix approach:** Add a demote pass inside `get_tools_for_list()` after scoring, using the scored results to identify low-rank tools that were not called this turn.

---

### K=15/K=18 Hardcoded in `pipeline.py` — `RetrievalConfig.top_k` Ignored

- **Issue:** `RetrievalConfig` (`src/multimcp/retrieval/models.py:42`) exposes `top_k: int = 15` as a config field, creating a clear operator-facing surface. However, `pipeline.get_tools_for_list()` (`src/multimcp/retrieval/pipeline.py:499-506`) hardcodes `dynamic_k = 15` and `dynamic_k = 18` directly in code, reading neither `self.config.top_k` nor `self.config.max_k`. The config field is effectively dead.
- **Impact:** Operators cannot tune retrieval K via config. The disconnect between the documented config surface and actual behavior is a latent confusion point.
- **Files:** `src/multimcp/retrieval/pipeline.py:499-506`, `src/multimcp/retrieval/models.py:42-48`
- **Fix approach:** Replace literal `15` with `self.config.top_k` and `18` with `self.config.top_k + 3`. Cap at `self.config.max_k`.

---

### ~~`mcp_client2.py` is Dead Code~~ ✅ RESOLVED (2026-03-30)

- **Was:** `mcp_client2.py` existed as an unwired upgrade to `mcp_client.py` with zero live imports.
- **Resolution:** `mcp_client2.py` content replaced `mcp_client.py` entirely. `mcp_client2.py` deleted. All 30+ import sites required zero changes (they already imported from `mcp_client`). 1032 tests pass after updating 2 test files for renamed internal methods.
- **Gains now live:** Concurrent discovery (~5s vs ~50s), deduplicated transport negotiation via `_negotiate_http_transport()`, exponential backoff with jitter in watchdog, transient/permanent error classification, per-server `AsyncExitStack` isolation.
- **Detail:** `.planning/debug/mcp-client-migration.md`

---

### `FileRetrievalLogger` Hardwired to `NullLogger` in Production

- **Issue:** The Phase 7 wiring in `multi_mcp.py:528` passes `logger=NullLogger()` to `RetrievalPipeline`. `FileRetrievalLogger` (which writes JSONL for offline replay evaluation, rollout gate checks, and the frequency-prior tier) is never instantiated in the production path. The frequency-prior retrieval tier (`_frequency_prior_tools`, `pipeline.py:309-387`) always returns `[]` because `getattr(self.logger, "_path", None)` returns `None` for `NullLogger`.
- **Impact:** The frequency-prior tier (Tier 4 in the fallback ladder) is silently non-functional in production. Replay evaluation (`src/multimcp/retrieval/replay.py`) has no log data to analyze. Rollout gate tooling (`check_cutover_gates`) cannot be validated.
- **Files:** `src/multimcp/multi_mcp.py:528`, `src/multimcp/retrieval/pipeline.py:319-321`, `src/multimcp/retrieval/logging.py:93-146`
- **Fix approach:** Instantiate `FileRetrievalLogger` with a path under `~/.local/share/multi-mcp/` or `~/.config/multi-mcp/` and wire it in `multi_mcp.py`. Make the log path configurable via `MCPSettings` or `RetrievalConfig`.

---

### `TelemetryScanner` Import Failure Silently Degrades Phase 7 Signal Quality

- **Issue:** `multi_mcp.py:519-523` wraps the `TelemetryScanner` instantiation in a broad `except Exception` block, logging a warning and falling through with `telemetry_scanner = None`. When `telemetry_scanner is None`, `pipeline.set_session_roots()` skips scanning entirely (`pipeline.py:182`), meaning no `WorkspaceEvidence` is populated for any session. The Tier 1 env-query path (which requires `workspace_evidence`) and the project-type static category path (Tier 2) both fall through, pushing sessions to Tier 3 (conversation context only) or lower on every turn.
- **Impact:** If `TelemetryScanner` fails to import (e.g., a missing transitive dependency), all sessions lose workspace-grounded signal. There is no metric or alert emitted to distinguish "scanner unavailable" from "workspace has no recognized project type." The degradation is invisible.
- **Files:** `src/multimcp/multi_mcp.py:517-523`, `src/multimcp/retrieval/pipeline.py:182-184`, `src/multimcp/retrieval/telemetry/scanner.py`
- **Fix approach:** Emit a `log_alert()` via the retrieval logger on scanner failure (once per startup, not per request). Add a pipeline health accessor that callers can inspect.

---

### SSE Profile Filter Save/Restore is Not Concurrent-Safe

- **Issue:** The SSE session handler in `multi_mcp.py:678-700` saves and restores `client_manager.tool_filters` as a shallow dict copy around each connection. The code comment acknowledges: `"save/restore is NOT concurrent-safe. Acceptable for single-user personal server; for multi-user deployments, use per-session filter copies."` If two SSE clients with different profiles connect simultaneously, their filter saves/restores will race.
- **Impact:** In multi-user or multi-session SSE deployments, one session's profile filters can leak into another session's tool visibility window.
- **Files:** `src/multimcp/multi_mcp.py:678-700`
- **Fix approach:** Replace the shared `client_manager.tool_filters` mutation with a per-session filter overlay passed directly to proxy methods, rather than mutating global state.

---

### Starlette and uvicorn Have No Version Constraints

- **Issue:** `pyproject.toml` declares `"starlette"` and `"uvicorn"` with no version bounds. Both projects have breaking changes between minor versions. The pinned `requirements.txt` shows `starlette==0.52.1` and `uvicorn==0.42.0`, but `pyproject.toml` would allow any version for fresh installs via `pip install`.
- **Impact:** Fresh installs may pull incompatible starlette/uvicorn versions and break SSE transport or Starlette routing.
- **Files:** `pyproject.toml:15-16`
- **Fix approach:** Add lower bounds: `"starlette>=0.40.0"`, `"uvicorn>=0.30.0"` (or tighter based on known-good range).

---

## Known Bugs

### Session State Dictionaries in `RetrievalPipeline` Never Evicted

- **Symptoms:** For every new SSE connection (each gets a unique `_get_session_id()` value), six per-session dicts in `RetrievalPipeline` grow unbounded: `_session_turns`, `_session_roots`, `_session_evidence`, `_session_tool_history`, `_session_arg_keys`, `_session_router_describes`. There is no cleanup hook called from `MCPProxyServer` on connection close.
- **Files:** `src/multimcp/retrieval/pipeline.py:164-171`, `src/multimcp/mcp_proxy.py` (no `clear_session` call)
- **Trigger:** Long-running SSE servers with many client reconnections.
- **Workaround:** Restart the server to release accumulated session state. `SessionStateManager.cleanup_session()` exists (`session.py:89`) but is never called from the pipeline or proxy.
- **Fix approach:** Hook into the SSE disconnect path (the `finally` block in `_SSEHandler.__call__`) to call `pipeline.clear_session(session_id)` (method does not exist yet — needs to be added).

---

## Security Considerations

### `langchain-mcp-adapters` is a Required Runtime Dependency but Unused in Core

- **Risk:** `pyproject.toml:21` lists `langchain-mcp-adapters` as a core (non-optional) dependency. This pulls in `langchain-core`, `langsmith`, and several other packages. No file in `src/multimcp/` imports from `langchain`. The dependency exists for `tests/` usage (e.g., `e2e_test.py`, `k8s_test.py`) but is installed for all users, including production deployments.
- **Files:** `pyproject.toml:21`, `tests/e2e_test.py`, `tests/k8s_test.py`
- **Current mitigation:** None — it's a dependency of the core package, not test-only.
- **Recommendation:** Move `langchain-mcp-adapters` (and `langgraph`) to `[project.optional-dependencies]` test section, which already exists at `pyproject.toml:24`.

---

## Performance Bottlenecks

### BMXFRetriever Index Not Rebuilt After Dynamic Server Add/Remove

- **Issue:** When servers are dynamically added or removed via `/mcp_servers` (POST/DELETE), `MCPProxyServer` calls `initialize_single_client()` / `_on_server_disconnected()` to update `tool_to_server`. However, `bmxf_retriever.rebuild_index()` is not called after dynamic changes — only at startup (`multi_mcp.py:514-515`). The retrieval index becomes stale.
- **Files:** `src/multimcp/multi_mcp.py:514-515`, `src/multimcp/mcp_proxy.py:538-545`, `src/multimcp/retrieval/bmx_retriever.py`
- **Cause:** The `_on_server_reconnected` callback (`multi_mcp.py:538-545`) calls `initialize_single_client` and `_send_tools_list_changed` but does not call `retrieval_pipeline.retriever.rebuild_index()`.
- **Improvement path:** Add `retrieval_pipeline.retriever.rebuild_index(proxy.tool_to_server)` to both the reconnect callback and the `_on_server_disconnected` handler.

---

## Fragile Areas

### `multi_mcp.py` Phase 7 Wiring Block Has No Test Coverage

- **Files:** `src/multimcp/multi_mcp.py:490-535`
- **Why fragile:** The block that wires `RetrievalPipeline`, `BMXFRetriever`, `SessionStateManager`, `TelemetryScanner`, and `NullLogger` into the proxy is inside `MultiMCP.run()` behind a `try` block. Tests (`test_startup_flow.py`, `test_retrieval_integration.py`) exercise `_bootstrap_from_yaml` and proxy integration separately, but no test exercises the full `run()` path including retrieval wiring. The three-test `test_startup_flow.py` only covers `_bootstrap_from_yaml` — it never invokes `run()`.
- **Safe modification:** Any change to the wiring block (`multi_mcp.py:490-535`) requires manual verification via `tests/runtime_check.py` (which does spin up a live server) or `tests/e2e_test.py`.
- **Test coverage:** The wiring block is covered only by integration/runtime scripts, not the pytest suite.

### Dynamic Server Add/Remove (SSE) Has No Pytest Coverage

- **Files:** `src/multimcp/mcp_proxy.py:887-1023` (`handle_mcp_control`), `src/multimcp/multi_mcp.py:793-838`
- **Why fragile:** The POST `/mcp_servers` and DELETE `/mcp_servers/{name}` flows are tested only in `tests/runtime_check.py` (Phase 8 block, lines 660-726), which is a manual integration script, not a pytest test. No file in the pytest suite exercises these endpoints against a running `MCPProxyServer`.
- **Safe modification:** Changes to dynamic server add/remove logic require manual runtime validation.
- **Test coverage:** Zero automated pytest coverage.

---

## Test Coverage Gaps

### `mcp_client.py` Reconnect / Watchdog Path

- **What's not tested:** The exponential backoff watchdog in `src/multimcp/mcp_client.py` and its `on_server_reconnected` callback chain (defined in `multi_mcp.py:538-547`) are not covered by the pytest suite. `tests/test_reconnect.py` exists but uses mocks rather than triggering real reconnect.
- **Files:** `src/multimcp/mcp_client.py` (watchdog logic), `src/multimcp/multi_mcp.py:537-547`
- **Risk:** A regression in reconnect-triggered proxy update (index rebuild, `tools/list_changed`) would be silent.
- **Priority:** Medium

### Retrieval Pipeline Session State Eviction

- **What's not tested:** No test verifies that session state is cleaned up on connection close, nor that the pipeline correctly handles the `cleanup_session` → `_session_turns` / history dict removal path.
- **Files:** `src/multimcp/retrieval/pipeline.py:164-171`
- **Risk:** Memory leak in long-running SSE servers goes undetected.
- **Priority:** Medium

### `FileRetrievalLogger` Frequency-Prior Integration

- **What's not tested:** No test validates that the frequency-prior tier (`_frequency_prior_tools`) returns results when `FileRetrievalLogger` is in use. All existing logger tests (`tests/test_file_retrieval_logger.py`) test JSONL write behavior but not the read-back path in `pipeline._frequency_prior_tools()`.
- **Files:** `src/multimcp/retrieval/pipeline.py:309-387`
- **Risk:** Frequency-prior silently returns empty list if log format or path changes.
- **Priority:** Low (tier is currently inactive due to `NullLogger` wiring)

---

## Dependencies at Risk

### `mcp>=1.26.0` Pinned to a Recent Major API

- **Risk:** The MCP SDK is rapidly evolving. The codebase uses `mcp.server.sse.SseServerTransport`, `mcp.client.streamable_http`, `mcp.server.session.ServerSession.list_roots()`, and other APIs that have changed between minor versions. The `>=1.26.0` lower bound without an upper bound means a `1.27.0` or `2.0.0` release could break the SSE transport wiring silently.
- **Files:** `pyproject.toml:10`, `src/multimcp/mcp_proxy.py` (SSE transport usage), `src/multimcp/mcp_client.py` (client session APIs)
- **Impact:** Broken SSE transport or client session creation on version upgrade.
- **Migration plan:** Add upper bound `mcp>=1.26.0,<2.0.0` or monitor the MCP changelog aggressively.

---

*Concerns audit: 2026-03-29*
