---
status: investigating
trigger: "concerns-app-layer: Four confirmed bugs/issues in the app layer and project configuration"
created: 2025-01-27T00:00:00Z
updated: 2025-01-27T00:00:00Z
symptoms_prefilled: true
---

## Current Focus

hypothesis: Six confirmed issues (D, E, F, G, H, I) need to be fixed in app layer files
test: Read source files, apply targeted fixes, run tests
expecting: All issues resolved, tests pass
next_action: Read all relevant source files before making changes

## Symptoms

expected: FileRetrievalLogger active in production, retrieval index stays fresh after dynamic server changes, dead code removed, dependency bounds correct
actual: four confirmed deviations (NullLogger hardwired, stale BMXF index, dead mcp_client2.py, no version bounds, langchain in core deps, missing cleanup_session call)
errors: no crashes — one silent data loss (NullLogger), one stale-index bug, two project hygiene issues
reproduction: read the source files listed per issue
started: discovered post Phase 7 audit via codebase mapping

## Eliminated

(none yet)

## Evidence

(none yet)

## Resolution

root_cause: Six confirmed issues in multi_mcp.py, mcp_client2.py, mcp_proxy.py, and pyproject.toml
fix: (in progress)
verification: (pending)
files_changed: []
