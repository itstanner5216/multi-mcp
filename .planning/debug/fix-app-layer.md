---
status: resolved
trigger: "Fix four confirmed bugs in the app layer and project config"
created: 2025-07-14T00:00:00Z
updated: 2025-07-14T00:00:00Z
---

## Files Changed

- `src/multimcp/multi_mcp.py`
- `src/multimcp/mcp_proxy.py`
- `pyproject.toml`

## Fix Summaries

### Issue D — Wire FileRetrievalLogger in production
**File:** `src/multimcp/multi_mcp.py`
Replaced `NullLogger()` passed to `RetrievalPipeline` with `FileRetrievalLogger(Path("logs/retrieval_rankings.jsonl"))`, wrapped in try/except to fall back to `NullLogger` on failure; pre-creates the `logs/` directory before construction. Also stored `bmxf_retriever` as `self.bmxf_retriever` for use by dynamic handlers.

### Issue E — Rebuild BMXF index after dynamic server add/remove
**File:** `src/multimcp/multi_mcp.py`
Added `self.bmxf_retriever.rebuild_index(self.proxy.tool_to_server)` after both the POST `/mcp_servers` eager-connect path (add) and the DELETE `/mcp_servers/{name}` unregister path (remove). `rebuild_index` is synchronous — no `asyncio.to_thread()` needed. Also initialised `self.bmxf_retriever = None` in `__init__` so the guard is safe before startup.

### Issue G — Version lower bounds for starlette and uvicorn
**File:** `pyproject.toml`
Changed `"starlette"` → `"starlette>=0.52.1"` and `"uvicorn"` → `"uvicorn>=0.42.0"`, using pinned versions from `requirements.txt` as the floor.

### Issue H — Move langchain-mcp-adapters to optional test deps
**File:** `pyproject.toml`
Removed `"langchain-mcp-adapters"` from `[project.dependencies]` and added it to `[project.optional-dependencies] test`. Makefile has no `pip install -e .` targets — no Makefile change required. Confirmed zero `langchain` usage in `src/` via grep.

### Issue I — Wire cleanup_session() on disconnect
**File:** `src/multimcp/mcp_proxy.py`
Added cleanup call just before `self._server_session = None` in the `run()` override's session teardown block:
```python
if self.retrieval_pipeline is not None and hasattr(self.retrieval_pipeline, "cleanup_session"):
    self.retrieval_pipeline.cleanup_session(self._get_session_id())
```
The `hasattr` guard ensures safety if the retrieval layer hasn't landed the method yet.

## Test Results

`uv run pytest tests/ -q --ignore=tests/e2e_test.py --ignore=tests/k8s_test.py`
→ **1032 passed in 18.75s**
