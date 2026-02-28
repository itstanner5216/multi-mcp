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

## Fixes Applied to Unowned Files (session 2)

### `src/multimcp/mcp_trigger_manager.py`

- **Exception handler too narrow** — `except (ConnectionError, TimeoutError, OSError,
  ValueError, RuntimeError)` missed `KeyError` (raised by `get_or_create_client`
  when a server disappears between the snapshot and the connect call) and any
  other edge-case exceptions.
  - Fix: Changed to `except Exception as e:` (does NOT swallow `SystemExit` or
    `KeyboardInterrupt` — these are `BaseException` subclasses).
  - Test added: `test_trigger_manager_catches_key_error`

### `src/multimcp/yaml_config.py`

- **`save_config` had no error handling** — any `OSError` (disk full, permissions)
  propagated as an unhandled exception with no log message, crashing startup.
  - Fix: Wrapped both `mkdir` and `open` calls in `try/except OSError` — logs
    the error clearly, then re-raises so callers can decide how to handle it.
  - Tests added: `test_save_config_raises_on_write_error`,
    `test_save_config_logs_and_raises_on_mkdir_error`

---

## Bugs Found Outside Scope (for owning agents)

### CLI agent scope (`mcp_proxy.py`, `multi_mcp.py`)

1. **`mcp_proxy.py:unregister_client` leaks server stack** (HIGH) — When a server
   is removed via `DELETE /mcp_servers/{name}`, `unregister_client` removes the
   client from `client_manager.clients` and cleans runtime state, but never calls
   `client_manager.server_stacks.pop(name)` nor `stack.aclose()`. The underlying
   stdio subprocess or SSE socket stays open until GC collects it.
   - Fix: Add before the `had_tools` check:
     ```python
     stack = self.client_manager.server_stacks.pop(name, None)
     if stack:
         asyncio.create_task(stack.aclose())
     ```

2. **`multi_mcp.py:handle_mcp_servers` POST — server in both clients and pending_configs**
   (LOW) — `add_pending_server` puts the server in `pending_configs`, then
   `create_clients` in eager mode connects it (setting `clients[name]`) but never
   removes it from `pending_configs`. Server ends up in both dicts. Not
   operationally harmful (fast path in `get_or_create_client` short-circuits), but
   `health` endpoint double-counts the server.
   - Fix: In `create_clients` eager path (or in `_create_single_client` success
     path), pop the name from `pending_configs`:
     `self.pending_configs.pop(name, None)`

3. **`multi_mcp.py` save_config callers need try/except** — Both `_first_run_discovery`
   and `_discover_new_servers` call `save_config` without error handling. Now that
   `save_config` re-raises `OSError`, a disk/perms failure crashes startup. Callers
   should wrap in `try/except OSError` and log a warning, then continue — the server
   can run without persisting the config.

4. **Shell-script commands blocked by `_validate_command`**: User's `servers.yaml`
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
