---
status: resolved
trigger: "mcp_client2.py identified as planned upgrade to mcp_client.py, not dead code"
created: 2026-03-30
updated: 2026-03-30
---

## Summary

`mcp_client2.py` was incorrectly flagged as dead code by the codebase mapper. On investigation
against the source implementation (not just the filename), it was confirmed to be a fully
implemented, production-ready upgrade to `mcp_client.py`. The migration was completed in this
session before any agents could delete it.

## Root Cause of Confusion

The codebase mapper saw zero imports of `mcp_client2` in `src/` or tests and labeled it dead
code. The correct read: it was a finished but un-wired replacement — waiting to be swapped in,
not waiting to be deleted.

## What mcp_client2.py Added Over mcp_client.py

1. **Concurrent discovery** — `discover_all()` uses `asyncio.gather` bounded by a connection
   semaphore; N servers complete in ~5s instead of ~50s sequential.
2. **Deduplicated transport negotiation** — Single `_negotiate_http_transport()` replaces three
   near-identical try/except blocks for Streamable HTTP → SSE fallback.
3. **Exponential backoff with jitter** — Watchdog retries use capped backoff (1s → 60s cap)
   instead of fixed 30s intervals. Reduces log noise for persistently dead servers.
4. **Structured error classification** — `_is_transient_error()` distinguishes retryable
   failures (timeout, connection reset) from permanent ones (bad command, SSRF rejection).
   Watchdog only retries transient errors.
5. **Per-server AsyncExitStack isolation** — Resolves the acknowledged TODO in the old
   `mcp_client.py:772`: "A future improvement would be per-server AsyncExitStack instances
   for full isolation." One server's cleanup failure can no longer affect others.

## Migration Steps Performed

1. Confirmed all public symbols used across the codebase exist in `mcp_client2.py`:
   - `MCPClientManager`, `_filter_env`, `_validate_command`, `_validate_url`,
     `PROTECTED_ENV_VARS`, `_PRIVATE_RANGES`, `DEFAULT_ALLOWED_COMMANDS`
2. Replaced `src/multimcp/mcp_client.py` content with `src/multimcp/mcp_client2.py` content
   via `cp src/multimcp/mcp_client2.py src/multimcp/mcp_client.py`
3. Deleted `src/multimcp/mcp_client2.py`
4. No import changes required anywhere — all 30+ import sites already used `mcp_client`

## Test Fixes Required

Two test files needed updates due to API changes in the new implementation:

### `tests/test_lifecycle_fixes.py`
- `_make_mgr()` uses `MCPClientManager.__new__()` to bypass `__init__` and manually sets
  attributes. The new client adds `_reconnect_backoff: Dict[str, float] = {}` in `__init__`,
  which `cleanup_server_state()` references. Added `mgr._reconnect_backoff = {}` to the helper.

### `tests/test_transport_consistency.py`
- All 14 tests referenced old method names that were refactored away:
  - `_discover_sse(name, url, server_config)` → `_discover_http(name, url, server_config)`
  - `_connect_url_server(name, url, env, stack, server_config)` → `_negotiate_http_transport(name, url, stack, transport_type)`
- Updated all call sites, patch targets, docstrings, and class-level docstrings.

## Verification

```
uv run pytest tests/ -q --ignore=tests/e2e_test.py --ignore=tests/k8s_test.py
1032 passed in 19.01s
```

## Files Changed

| File | Change |
|---|---|
| `src/multimcp/mcp_client.py` | Replaced with mcp_client2 implementation |
| `src/multimcp/mcp_client2.py` | **Deleted** (content migrated into mcp_client.py) |
| `tests/test_lifecycle_fixes.py` | Added `_reconnect_backoff = {}` to `_make_mgr()` |
| `tests/test_transport_consistency.py` | Updated all 14 tests to new method names |
