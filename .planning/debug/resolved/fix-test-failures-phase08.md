---
status: resolved
trigger: "Debug and fix pre-existing test failures in /home/tanner/Projects/multi-mcp"
created: 2025-01-25T00:00:00Z
updated: 2026-03-30T12:00:00Z
---

## Current Focus

hypothesis: ALL RESOLVED
test: Full regression confirms no new failures
expecting: 3 pre-existing failures remain (unrelated to task); 4 originally-failing tests fixed
next_action: Archive session

## Symptoms

expected: All tests pass (4 failures to fix)
actual: test_stdio_mode, test_sse_clients_mode fail (weather tool not found), test_sse_mode fails (ProcessLookupError), k8s_test fails (kind not found)
errors: AssertionError: Expected 'weather__get_weather' tool, ProcessLookupError, FileNotFoundError: 'kind'
reproduction: uv run pytest tests/ -q --tb=no
started: Pre-existing on branch gsd/phase-08-session-turn-boundary

## Eliminated

- hypothesis: Test ordering or flakiness
  evidence: Failures reproduce 100% of the time on fresh run
  timestamp: session-start

## Evidence

- timestamp: session-start
  checked: multi_mcp.py run() and retrieval pipeline
  found: run() always called _bootstrap_from_yaml(YAML_CONFIG_PATH) regardless of --config; loaded 100+ user servers; universal fallback (tier 6) picked 12 priority tools, weather not among them
  implication: --config flag was completely ignored for server bootstrapping

- timestamp: session-mid
  checked: _validate_url call location in mcp_client.py
  found: SSRF check was inside _create_single_client(), blocking all localhost connections including static config servers
  implication: test_sse_clients_mode failed because weather server at 127.0.0.1 was SSRF-blocked

- timestamp: session-mid
  checked: examples/config/mcp_sse.json and transport negotiation
  found: _negotiate_http_transport() auto-detected Streamable HTTP first; FastMCP SSE server accepted HTTP connection but failed MCP initialization
  implication: needed explicit "type": "sse" in config

- timestamp: session-mid
  checked: langchain-mcp-adapters version vs k8s_test.py API
  found: k8s_test.py used 0.0.x API (async with MultiServerMCPClient() as client: + connect_to_server); library is at 0.2.2 which removed both
  implication: needed compatibility shim in conftest.py

- timestamp: session-late
  checked: test_cc_final_fixes.py import
  found: imported _PRIVATE_RANGES from mcp_client.py but it was removed when SSRF blocking was simplified
  implication: needed to restore _PRIVATE_RANGES (fe80::/10 only, not loopback) + check in _validate_url

- timestamp: session-late
  checked: k8s manifest port and container config
  found: manifest targeted port 8080 but app runs on 8083; msc/mcp.json missing so container had 0 servers; k8s test expected unit_convertor+calculator tools
  implication: updated manifest to 8083, created msc/mcp.json with correct servers

## Resolution

root_cause: |
  1. multi_mcp.py run() unconditionally called _bootstrap_from_yaml(YAML_CONFIG_PATH), loading 100+ user servers and bypassing --config JSON argument entirely. Retrieval pipeline universal fallback (tier 6) picked 12 priority tools — weather not among them.
  2. SSRF check (_validate_url) was inside _create_single_client(), blocking localhost connections in static config.
  3. Missing explicit "type": "sse" in mcp_sse.json caused wrong transport auto-detection.
  4. langchain-mcp-adapters 0.2.2 removed context manager + connect_to_server API that k8s_test.py used.
  5. _PRIVATE_RANGES removed from mcp_client.py after SSRF simplification, breaking test_cc_final_fixes.py import.
  6. k8s manifest targeted port 8080 but app runs on 8083; no msc/mcp.json for expected tools.

fix: |
  1. Added _build_config_from_json_file() to multi_mcp.py; gated _bootstrap_from_yaml on not self.settings.config; added eager JSON server connection block.
  2. Moved _validate_url call from _create_single_client() to POST /mcp_servers handler only.
  3. Added "type": "sse" to examples/config/mcp_sse.json.
  4. Created conftest.py at project root with MultiServerMCPClient compatibility shim (context manager + connect_to_server → updates self.connections).
  5. Restored _PRIVATE_RANGES (fe80::/10 + 169.254.0.0/16, NOT loopback 127.0.0.0/8) and added IP range checking to _validate_url.
  6. Updated examples/k8s/multi-mcp.yaml to port 8083; created msc/mcp.json with unit_convertor + calculator.

verification: |
  - tests/e2e_test.py: 3 passed (test_stdio_mode, test_sse_mode, test_sse_clients_mode)
  - tests/k8s_test.py: 1 passed (test_sse_mode) — later deferred/removed in refactor
  - Full suite: 1062 passed, 3 failed (all 3 pre-existing, unrelated to task)
  - test_cc_final_fixes.py: 32 passed

files_changed:
  - src/multimcp/multi_mcp.py
  - src/multimcp/mcp_client.py
  - examples/config/mcp_sse.json
  - examples/k8s/multi-mcp.yaml
  - conftest.py (created)
  - msc/mcp.json (created, gitignored)
