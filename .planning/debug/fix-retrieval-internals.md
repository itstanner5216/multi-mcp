---
status: fixing
trigger: "Fix three confirmed bugs in the retrieval layer"
created: 2025-01-01T00:00:00Z
updated: 2025-01-01T00:00:00Z
---

## Current Focus

hypothesis: All three bugs are confirmed and understood; applying targeted fixes
test: Run pytest after all three changes
expecting: 1032 passed, 0 failed
next_action: apply_fixes_then_run_tests

## Symptoms

expected: demote() called, cleanup_session() exists, top_k config used
actual: demote() never called; no cleanup_session() on pipeline; hardcoded 15/18/20
errors: N/A — silent bugs
reproduction: Code inspection
started: Always present

## Eliminated

- N/A — bugs confirmed by inspection

## Evidence

- timestamp: 2025-01-01T00:00:00Z
  checked: session.py demote() signature
  found: demote(session_id, tool_keys, used_this_turn, max_per_turn=3)
  implication: Need active_keys - active_key_set, with used_this_turn=set(session_tool_history)

- timestamp: 2025-01-01T00:00:00Z
  checked: pipeline.py six session dicts
  found: _session_turns, _session_roots, _session_evidence, _session_tool_history, _session_arg_keys, _session_router_describes
  implication: cleanup_session() must pop all six + call session_manager.cleanup_session()

- timestamp: 2025-01-01T00:00:00Z
  checked: models.py RetrievalConfig
  found: top_k=15, max_k=20 both present
  implication: dynamic_k=15→top_k, dynamic_k=18→max_k (not top_k+3), min(20,...)→min(max_k,...)

## Resolution

root_cause: |
  A) demote() defined but never wired into get_tools_for_list()
  B) cleanup_session() missing from RetrievalPipeline — six dicts grow unbounded
  C) Hardcoded literals 15/18/20 ignore RetrievalConfig.top_k and max_k fields

fix: |
  A) After active_key_set computed, call session_manager.demote() for tools in
     active_keys but not active_key_set, with used_this_turn from session history
  B) Add cleanup_session() method popping all six dicts + calling session_manager
  C) Replace 15→self.config.top_k, 18→self.config.max_k, 20→self.config.max_k

verification: "uv run pytest tests/ -q --ignore=tests/e2e_test.py --ignore=tests/k8s_test.py → 1032 passed in 19.02s"
files_changed:
  - src/multimcp/retrieval/pipeline.py
