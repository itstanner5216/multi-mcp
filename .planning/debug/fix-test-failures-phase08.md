---
status: investigating
trigger: "Debug and fix pre-existing test failures in /home/tanner/Projects/multi-mcp"
created: 2025-01-25T00:00:00Z
updated: 2025-01-25T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED - YAML always loads 100+ user servers; retrieval pipeline universal fallback picks 12 priority tools (not weather); SSE failure is secondary consequence; kind not installed
test: Fix _build_config_from_json_file + gate YAML bootstrap + eager JSON server connection
expecting: weather+calculator are only 3 tools total → all returned by retrieval pipeline
next_action: Apply fix to multi_mcp.py, then handle k8s with conftest.py

## Symptoms

expected: All tests pass (4 failures to fix)
actual: test_stdio_mode, test_sse_clients_mode fail (weather tool not found), test_sse_mode fails (ProcessLookupError), k8s_test fails (kind not found)
errors: AssertionError: Expected 'weather__get_weather' tool, ProcessLookupError, FileNotFoundError: 'kind'
reproduction: uv run pytest tests/ -q --tb=no
started: Pre-existing on branch gsd/phase-08-session-turn-boundary

## Eliminated

## Evidence

## Resolution

root_cause:
fix:
verification:
files_changed: []
