---
status: awaiting_human_verify
trigger: "Phase 7 (Roots-Anchored BMXF Routing) has 7 confirmed deviations from plan"
created: 2025-01-30T00:00:00Z
updated: 2025-01-30T00:00:00Z
---

## Current Focus

hypothesis: All 7 deviations are confirmed — applying fixes in dependency order
test: Apply each fix, then run test suite
expecting: All tests pass, deviations resolved
next_action: Apply Issue 3 first (models.py timestamp), then Issues 4/5/7 (pipeline.py), then Issue 2 (pipeline + proxy), then Issue 6 (proxy session ID), then Issue 1 (multi_mcp.py wiring)

## Symptoms

expected: Phase 7's retrieval pipeline is fully live, wired into the real app runtime, with correct session tracking, honest telemetry, and faithful adherence to the K-slot design.
actual: 7 confirmed deviations from plan — pipeline disabled, session IDs wrong, K-slot off-by-one, alpha wrong, timestamp missing, describe not recorded, promote on wrong boundary.
errors: No crashes — behavioral/architectural deviations.
reproduction: Read source files listed in confirmed_issues.
started: Post Phase 7 implementation; discovered during audit before Phase 8.

## Eliminated

(none — all 7 issues are confirmed, no investigation needed)

## Evidence

- timestamp: 2025-01-30T00:00:00Z
  checked: multi_mcp.py:494-512
  found: RetrievalConfig(enabled=False, shadow_mode=True); no rebuild_index call; NullLogger; no TelemetryScanner passed
  implication: Issue 1 confirmed — pipeline fully disabled at runtime

- timestamp: 2025-01-30T00:00:00Z
  checked: mcp_proxy.py:437-456
  found: describe=True routing path returns directly without recording to _session_router_describes
  implication: Issue 2 confirmed — router describes never written to session state

- timestamp: 2025-01-30T00:00:00Z
  checked: models.py RankingEvent + pipeline.py:347-360 + pipeline.py:649-665
  found: RankingEvent has no timestamp field; Tier 5 parser admits via comment that no timestamp exists; direct_tool_calls/router_proxies never populated at emission
  implication: Issue 3 confirmed — frequency prior not fed by real ranking logs; no temporal decay

- timestamp: 2025-01-30T00:00:00Z
  checked: pipeline.py:657
  found: alpha=ws_confidence instead of computed fusion alpha from _compute_alpha()
  implication: Issue 4 confirmed — RankingEvent.alpha is approximate/wrong

- timestamp: 2025-01-30T00:00:00Z
  checked: pipeline.py:503-507
  found: direct_k = dynamic_k - 1 when routing_tool_enabled
  implication: Issue 5 confirmed — routing tool steals a K slot from retrieval results

- timestamp: 2025-01-30T00:00:00Z
  checked: mcp_proxy.py:530-531
  found: on_tool_called("default", ...) — hardcoded "default" session ID
  implication: Issue 6 confirmed — session-grounded conversation signal broken

- timestamp: 2025-01-30T00:00:00Z
  checked: pipeline.py:704-735
  found: on_tool_called increments _session_turns AND calls session_manager.promote() per-call
  implication: Issue 7 confirmed — promote happens per tool call, not per turn boundary

## Resolution

root_cause: Seven discrete implementation deviations from the Phase 7 plan spec, each independently introduced during implementation.
fix: |
  Issue 1 (multi_mcp.py): Changed RetrievalConfig to enabled=True, shadow_mode=False, rollout_stage="ga";
    added bmxf_retriever.rebuild_index() call after proxy init; added TelemetryScanner construction and wiring.
  Issue 2 (pipeline.py + mcp_proxy.py): Added record_router_describe() method to RetrievalPipeline;
    called it from mcp_proxy._call_tool() after describe=True routing succeeds.
  Issue 3 (models.py + pipeline.py): Added timestamp: float = field(default_factory=time.time) to RankingEvent;
    updated Tier 5 parser to use event.get("timestamp") directly (clean, no workarounds);
    populated direct_tool_calls/router_proxies from session history at RankingEvent emission.
  Issue 4 (pipeline.py): Replaced alpha=ws_confidence approximation with fusion_alpha variable
    that captures the real _compute_alpha() result from Tier 1; uses fusion_alpha in RankingEvent.
  Issue 5 (pipeline.py): Changed direct_k = max(1, dynamic_k - 1) to direct_k = dynamic_k;
    routing tool is now additive, not a K-slot consumer.
  Issue 6 (mcp_proxy.py): Replaced hardcoded "default" with self._get_session_id() in on_tool_called.
  Issue 7 (pipeline.py + tests): Removed turn increment and session_manager.promote() from on_tool_called;
    moved both to get_tools_for_list() (true turn boundary); updated 7 tests that encoded old behavior.
verification: All 1031 tests pass (uv run pytest, ignoring langchain e2e tests with missing deps).
files_changed:
  - src/multimcp/retrieval/models.py
  - src/multimcp/retrieval/pipeline.py
  - src/multimcp/mcp_proxy.py
  - src/multimcp/multi_mcp.py
  - tests/test_pipeline_phase3.py
