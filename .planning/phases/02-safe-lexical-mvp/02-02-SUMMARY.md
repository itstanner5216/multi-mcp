---
phase: 02-safe-lexical-mvp
plan: "02"
subsystem: retrieval
tags:
  - routing-tool
  - assembler
  - bounded-active-set
  - tdd
dependency_graph:
  requires:
    - 02-01 (models, TieredAssembler baseline)
  provides:
    - routing_tool.py (ROUTING_TOOL_NAME, build_routing_tool_schema, format_namespace_grouped, handle_routing_call)
    - TieredAssembler.assemble(routing_tool_schema=) optional param
    - tests/test_routing_tool.py (22 tests, all passing)
  affects:
    - assembler.py (backward-compatible extension)
tech_stack:
  added: []
  patterns:
    - "Synthetic MCP tool as routing safety valve for bounded active set"
    - "Optional param pattern for backward-compatible assembler extension"
    - "Namespace-grouped ordering: env namespaces first, then alphabetical"
key_files:
  created:
    - src/multimcp/retrieval/routing_tool.py
    - tests/test_routing_tool.py
  modified:
    - src/multimcp/retrieval/assembler.py
decisions:
  - "ROUTING_TOOL_KEY uses double-underscore prefix (__routing__request_tool) to match server__tool namespacing pattern"
  - "handle_routing_call returns __PROXY_CALL__:name sentinel for describe=False; async dispatch handled by caller"
  - "TieredAssembler.assemble routing_tool_schema param is Optional with None default for full backward compatibility"
metrics:
  duration: "478s (~8 min)"
  completed: "2026-03-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 1
---

# Phase 02 Plan 02: Routing Tool — Summary

**One-liner:** Synthetic `request_tool` MCP tool with enum-based demoted-tool catalog and TieredAssembler integration for bounded active set safety valve.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | routing_tool.py synthetic MCP routing tool | dfe5d41 | src/multimcp/retrieval/routing_tool.py |
| 2 | Update assembler.py + write tests/test_routing_tool.py | fb62931 | src/multimcp/retrieval/assembler.py, tests/test_routing_tool.py |

## What Was Built

### routing_tool.py

New module at `src/multimcp/retrieval/routing_tool.py` implementing:

- `ROUTING_TOOL_NAME = "request_tool"` — name constant
- `ROUTING_TOOL_KEY = "__routing__request_tool"` — storage key constant
- `build_routing_tool_schema(demoted_tool_ids)` — builds `types.Tool` with `name`, `describe` (boolean), and `arguments` (object) properties; `name` property carries the full enum of demoted tool IDs
- `format_namespace_grouped(tool_ids, env_namespaces)` — orders tool IDs with env-relevant namespace groups first (each sorted), then remaining groups alphabetically
- `handle_routing_call(name, describe, arguments, tool_to_server)` — returns schema JSON on `describe=True`, proxy sentinel string on `describe=False`, "Tool not found" message if tool key missing

### assembler.py (Updated)

Added `routing_tool_schema: Optional[types.Tool] = None` parameter to `TieredAssembler.assemble()`. When provided, routing tool is appended as the final element of the returned list. When `None` (default), behavior is identical to before.

### tests/test_routing_tool.py

22 tests covering:
- ROUTER-01: `ROUTING_TOOL_NAME` and `ROUTING_TOOL_KEY` constant values
- ROUTER-02: `build_routing_tool_schema` enum contents, required fields, property shapes, large enum (25 tools)
- ROUTER-03: `format_namespace_grouped` namespace ordering for env-first, alphabetical fallback, multiple env namespaces
- TEST-04: `handle_routing_call` describe=True schema JSON, missing tool error, describe=False proxy sentinel
- Integration: `TieredAssembler.assemble()` with and without routing tool, empty tools case, backward compat

## Verification

```
pytest tests/test_routing_tool.py    — 22 passed
pytest tests/test_tiered_assembler.py — 10 passed (no regressions)
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All routing tool functions are fully implemented. The `__PROXY_CALL__:name` sentinel in `handle_routing_call` is intentional — async proxy dispatch is handled by the caller layer (wired in a later plan).

## Self-Check: PASSED

All created files verified present. Both task commits verified in git log.
