# Wave 3 Pre-Execution Context

## What We're Doing
Multi-agent stabilization of multi-mcp (Python MCP proxy server). Three agents work in parallel:
- **CLI (me/Copilot)**: `/home/tanner/Projects/multi-mcp` — hardest tasks
- **CC (Claude Code)**: `/home/tanner/Projects/multi-mcp-cc` — medium tasks  
- **OC (OpenCode)**: `/home/tanner/Projects/multi-mcp-oc` — simplest tasks

## Current State
- **Wave 1**: DONE (49 bugs fixed, 238 tests)
- **Wave 2**: DONE (all 3 agents pushed their branches)
  - CLI: `stabilize/cli-wave2` at `87b4e4b` (6 commits, mcp_proxy.py fixes + 40 tests)
  - CC: `stabilize/cc-wave2` at `b51f7e7` (6 commits, security hardening)
  - OC: `stabilize/oc-wave2` at `20abeae` (6 commits, config/audit/trigger fixes)
  - File overlap between branches: ZERO — merge should be conflict-free
- **Wave 3**: Plans written, ready to execute
- **Wave 4**: Not planned yet (final production hardening)

## Wave 3 Plans (located at /home/tanner/Projects/multi-mcp-plans/)
- `CLI-wave3.md`: Merge Wave 2 + build entire retrieval package (Phase 3 from original plan)
- `CC-wave3.md`: KeywordRetriever TF-IDF + namespace filter + ranker (Phase 4 Tasks 1-3)
- `OC-wave3.md`: TieredAssembler + YAML config + pipeline wiring + E2E tests (Phase 4 Tasks 4-7)

## MY (CLI) Tasks in Wave 3
1. **Merge Wave 2 branches** into `stabilize/integration`, verify tests, create `stabilize/cli-wave3`
2. **Create retrieval package** — `src/multimcp/retrieval/__init__.py` + `models.py`
3. **Abstract interfaces** — `base.py` (ToolRetriever ABC, PassthroughRetriever) + `logging.py` (RetrievalLogger ABC, NullLogger)
4. **SessionStateManager** — `session.py` with monotonic per-session tool sets
5. **RetrievalPipeline** — `pipeline.py` orchestrator (get_tools_for_list + on_tool_called placeholder)
6. **Integrate into MCPProxyServer** — modify `mcp_proxy.py` and `multi_mcp.py`
7. **Verify + push**

## Critical Technical Details
- Python 3.11, run with `uv run python` (NOT bare python)
- Test: `uv run python -m pytest tests/ --ignore=tests/e2e_test.py --ignore=tests/k8s_test.py --ignore=tests/lifecycle_test.py -q`
- Base branch: `stabilize/integration` at `2d669ba`
- Git remote: `github.com:itstanner5216/multi-mcp.git`
- Resources use raw URIs (can't namespace with Pydantic AnyUrl)
- MagicMock(name="X") sets internal mock name, not .name attribute
- ServerResult is Pydantic RootModel — access via result.root.isError

## File Ownership (DO NOT TOUCH other agents' files)
- CLI owns: `mcp_proxy.py`, `retrieval/__init__.py`, `retrieval/models.py`, `retrieval/base.py`, `retrieval/logging.py`, `retrieval/session.py`, `retrieval/pipeline.py`
- CC owns: `retrieval/namespace_filter.py`, `retrieval/keyword.py`, `retrieval/ranker.py`
- OC owns: `retrieval/assembler.py`, `yaml_config.py` (modify), `retrieval/pipeline.py` (modify after CLI creates it)

## Worktree Collision Warning
In Wave 2, all 3 agents worked in the same directory and contaminated each other's branches. Fixed by creating separate worktrees. Plans include stern warnings. Each agent MUST verify `pwd` and `git branch --show-current` before every commit.

## Required Plan Disclaimers (user demands these in every plan)
1. 🚨 OWNERSHIP RULE — own quality of entire codebase, document ALL errors
2. 🚨 WORKTREE SAFETY — stern collision warning
3. Skill activations: subagent-driven-development, using-git-worktrees, executing-plans, receiving-code-review, systematic-debugging, verification-before-completion
4. Subagent prompt must include explicit worktree path and branch verification

## User Preferences
- ~$800 in API fees — wants quality but efficiency
- Plans: CLI=hardest, CC=medium, OC=simplest
- User will compact conversation before execution starts
- Wave 4 comes after Wave 3 (final exhaustive production hardening)
