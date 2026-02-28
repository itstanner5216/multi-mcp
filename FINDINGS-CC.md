# CC Agent Findings

## Status: Phase 1 + Phase 2 + Phase 3 Complete

Branch: `stabilize/cc-final`
Commit: `12a9cf8`
Tests: 491 passing (baseline was 459; +32 new regression tests)

---

## Bugs Fixed (in scope)

### `src/multimcp/mcp_client.py`

1. **`get_or_create_client` — config lost on connection failure** (CRITICAL)
   - `pending_configs.pop(name)` ran before connection succeeded. If connection
     timed out or raised, the server was permanently unretryable.
   - Fix: Restore `pending_configs[name] = config` in both `TimeoutError` and
     `Exception` handlers.

2. **`_disconnect_idle_servers` — KeyError window during reconnection** (BUG)
   - `pending_configs[name]` was restored AFTER `await stack.aclose()`. Any
     `get_or_create_client` call in that window raised `KeyError`.
   - Fix: Restore `pending_configs` BEFORE all awaits (before `stack.aclose()`).

3. **`close()` — stale clients after close** (BUG)
   - `self.clients` was not cleared after stacks were closed. Callers could
     receive dead sessions via the fast path.
   - Fix: Added `self.clients.clear()` in `close()`.

4. **`_filter_env` — non-string env values** (BUG)
   - Config values could be int/bool/None. `StdioServerParameters` requires
     string values; passing non-strings causes `TypeError`.
   - Fix: Changed `v` → `str(v)` in the dict comprehension.

5. **`_PRIVATE_RANGES` — missing IPv6 link-local** (SECURITY)
   - `fe80::/10` was absent, allowing SSRF via IPv6 link-local addresses.
   - Fix: Added `ipaddress.ip_network("fe80::/10")` to the list.

### `src/multimcp/utils/audit.py`

6. **`_sanitize_arguments` — tuples/sets not sanitized** (BUG)
   - Tuples and sets were returned as-is without recursive sanitization, so
     sensitive keys inside tuples/sets were not redacted.
   - Fix: Added handlers for `tuple` and `(set, frozenset)` before the dict branch.

7. **`AuditLogger.close()` — AttributeError if sink never set** (BUG)
   - If `logger.add()` raised (e.g., bad log dir), `_sink_id` was never assigned
     and `close()` threw `AttributeError`.
   - Fix: Guard with `hasattr(self, "_sink_id")`.

8. **`_write_entry` — unprotected `json.dumps`** (BUG)
   - `default=str` is usually safe but can raise if `__str__` itself raises.
   - Fix: Wrapped in `try/except` with a safe fallback JSONL entry.

### `src/multimcp/utils/keyword_matcher.py`

9. **Unused `import json`** — removed.

### `src/multimcp/utils/config.py`

10. **Unused `from typing import Optional`** — removed.

---

## Public API Changes

**None.** No method signatures were changed. All fixes are internal behavior
changes. CLI agent (`mcp_proxy.py`, `multi_mcp.py`) does not need updates.

---

## Bugs Found Outside Scope (for owning agents)

### CLI agent scope (`mcp_proxy.py`, `multi_mcp.py`)

- **Shell-script commands blocked by `_validate_command`**: User's `servers.yaml`
  references shell scripts (e.g., `/home/tanner/mcp-servers/run-github.sh`).
  These are correctly rejected by the security validator. The user's config
  needs to be updated to use bare command names (e.g., `node`, `python`), or
  the validator's allowlist needs a deliberate extension. Documenting for CLI
  agent awareness — this is not a bug in CC scope but is visible in logs.

---

## Runtime Smoke Test Results

- **Stdio**: Server started, responded to `initialize` + `tools/list`, graceful
  shutdown. ✅
- **SSE port 8086**: Server bound, `/mcp_servers` returned `200 OK` with
  `{"active_servers":[]}`. ✅
- **Port 8086**: Confirmed free after test. ✅
- **No orphan processes** from this test run. ✅
