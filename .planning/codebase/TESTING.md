# Testing Patterns

**Analysis Date:** 2025-07-10

## Test Framework

**Runner:**
- `pytest` ≥ 9.0.2
- Config: `pyproject.toml` (`[tool.pytest.ini_options]`)

**Async Support:**
- `pytest-asyncio` ≥ 1.3.0
- `asyncio_mode = "auto"` — every `async def test_*` runs automatically under asyncio; no `@pytest.mark.asyncio` required on individual tests (though some legacy tests still carry the decorator)

**Assertion Library:**
- Standard `assert` statements (no third-party assertion library)

**Python Path:**
- `pythonpath = ["."]` — imports use `src.*` prefix from project root

**Run Commands:**
```bash
make test-proxy       # Core proxy functionality: pytest -s tests/proxy_test.py
make test-e2e         # End-to-end integration: pytest -s tests/e2e_test.py
make test-lifecycle   # Server lifecycle via HTTP API: pytest -s tests/lifecycle_test.py
make all-test         # All three suites in sequence

# Run any specific test file directly
pytest -s tests/test_retrieval_pipeline.py

# Run a single test
pytest -s tests/test_bmx_retriever.py::TestRebuildIndex::test_builds_index_from_registry
```

## Test File Organization

**Location:**
- All tests in `tests/` (flat, no subdirectories except `tests/BM25-Tests/` benchmarks and `tests/tools/`)
- No co-located tests alongside source files

**Naming:**
- `test_*.py` — unit/component tests (new convention): `test_retrieval_pipeline.py`, `test_bmx_retriever.py`
- `*_test.py` — legacy integration/e2e tests: `proxy_test.py`, `e2e_test.py`, `lifecycle_test.py`
- Test functions: `def test_<what_it_does>()`
- Test classes: `class Test<ComponentOrBehavior>:`

**Structure:**
```
tests/
├── proxy_test.py            # Core proxy unit tests (mock MCP servers)
├── e2e_test.py              # End-to-end: stdio + SSE mode via subprocess
├── lifecycle_test.py        # HTTP API lifecycle (add/remove servers)
├── test_retrieval_pipeline.py
├── test_bmx_retriever.py
├── test_rrf_fusion.py
├── test_core_pipeline_wiring.py
├── test_pipeline_bounded_k.py
├── ... (60+ test_*.py files for retrieval system)
├── tools/                   # Mock MCP tool servers used by integration tests
│   ├── calculator.py
│   ├── get_weather.py
│   ├── get_weather_sse.py
│   └── unit_convertor.py
├── BM25-Tests/              # Standalone benchmarks (not part of pytest suite)
│   ├── benchmark_bm_large.py
│   ├── benchmark_bm_medium.py
│   └── benchmark_bm_small.py
└── utils.py                 # Shared test helpers (run_e2e_test_with_client, get_chat_model)
```

## Test Structure

**Suite Organization (class-based, preferred for retrieval tests):**
```python
class TestRetrievalConfigTopKDefault:
    def test_retrieval_config_top_k_default(self):
        """RetrievalConfig().top_k must equal 15."""
        config = RetrievalConfig()
        assert config.top_k == 15

class TestPipelineDisabled:
    """When retrieval is disabled, pipeline returns all tools."""

    @pytest.mark.asyncio
    async def test_returns_all_connected_tools(self):
        config = RetrievalConfig(enabled=False)
        ...
        tools = await pipeline.get_tools_for_list("session-1")
        assert len(tools) == 2
```

**Function-based (proxy_test.py, lifecycle tests):**
```python
@pytest.mark.asyncio
async def test_proxy_lists_multiple_tools(server_1, server_2, test_tool_1, test_tool_2, test_tool_3):
    """Tests if proxy correctly aggregates tools from multiple servers."""
    async with proxy_client_2session(server_1, server_2) as proxy:
        result = await proxy.initialize()
        tools = await proxy.list_tools()
        assert result.capabilities.tools
        assert tool_names == {MCPProxyServer._make_key(SERVER1_NAME, test_tool_1.name), ...}
```

**Docstrings on test functions** (required for public-facing test files):
```python
async def test_proxy_call_tool(echo_server):
    """Tests if the proxy can call a tool and receive a response."""
```

## Mocking

**Framework:** `unittest.mock` — `AsyncMock`, `MagicMock`, `patch`

**Standard import pattern:**
```python
from unittest.mock import AsyncMock, MagicMock, patch
```

**ToolMapping mocks — use `MagicMock()` with explicit attributes:**
```python
def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()  # Non-None = connected
    return m

def _make_disconnected_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = None  # None = disconnected/cached
    return m
```

**Dataclass fakes — prefer `@dataclass` over `MagicMock` when attribute structure is fixed:**
```python
@dataclass
class FakeToolMapping:
    tool: types.Tool
    server_name: str = "test_server"
    client: object = None
```

**Logger mocks — use `NullLogger` from `src.multimcp.retrieval.logging`:**
```python
from src.multimcp.retrieval.logging import NullLogger
pipeline = RetrievalPipeline(..., logger=NullLogger(), ...)
```

**Patching with `patch`:**
```python
with patch("src.multimcp.retrieval.pipeline._HAS_FUSION", True):
    ...
```

**What to mock:**
- `ToolMapping` / client sessions (avoid real network connections)
- `NullLogger` for any component that takes a `RetrievalLogger`
- `AsyncMock` for coroutine methods called on mock objects

**What NOT to mock:**
- Core algorithm logic (`weighted_rrf`, `BMXFRetriever.retrieve`) — test with real implementations
- `RetrievalConfig` / `RetrievalContext` — construct directly with dataclass/model

## Fixtures and Factories

**pytest fixtures (proxy tests):**
```python
@pytest.fixture
def test_tool_1():
    """First mock tool."""
    return Tool(
        name="Tool1",
        description="first test tool",
        inputSchema={"type": "object", "properties": {}},
    )

@pytest_asyncio.fixture
async def server_1(test_tool_1):
    """Simulates a server with one tool."""
    server = Server(SERVER1_NAME)
    @server.list_tools()
    async def _():
        return [test_tool_1]
    return server
```

**In-memory MCP sessions (proxy tests) — use `create_connected_server_and_client_session`:**
```python
from mcp.shared.memory import create_connected_server_and_client_session

@asynccontextmanager
async def proxy_client_session(server):
    """Creates a proxy with a single backend server session."""
    async with create_connected_server_and_client_session(server) as direct_client:
        client_manager = MCPClientManager()
        client_manager.clients = {server.name: direct_client}
        proxy = await MCPProxyServer.create(client_manager)
        async with create_connected_server_and_client_session(proxy) as proxy_client:
            yield proxy_client
```

**Pipeline factory helpers (retrieval tests) — define `_make_pipeline()` per test file:**
```python
def _make_pipeline(
    registry: dict | None = None,
    config: RetrievalConfig | None = None,
    retriever=None,
) -> RetrievalPipeline:
    if config is None:
        config = RetrievalConfig(enabled=True, rollout_stage="ga")
    if registry is None:
        registry = _make_registry()
    if retriever is None:
        retriever = PassthroughRetriever()
    return RetrievalPipeline(
        retriever=retriever,
        session_manager=SessionStateManager(config),
        logger=NullLogger(),
        config=config,
        tool_registry=registry,
    )
```

**Registry builder helpers — define `_make_registry(n)` / `_build_registry(tools)` locally:**
```python
def _make_registry(n: int = 5) -> dict:
    return {
        f"srv{i}__{i}_tool": _make_mapping(f"srv{i}", _make_tool(f"{i}_tool"))
        for i in range(n)
    }
```

**Tool helpers — define `_make_tool(name, desc)` in each retrieval test file:**
```python
def _make_tool(name: str, desc: str = "A tool") -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": {}},
    )
```

**No shared `conftest.py`** — fixtures are defined per test file or as module-level helper functions.

**Test data:** `tests/tools/` contains real runnable MCP servers (not fixtures):
- `tests/tools/calculator.py` — MCP calculator server (stdio)
- `tests/tools/get_weather.py` — MCP weather server (stdio)
- `tests/tools/get_weather_sse.py` — MCP weather server (SSE)
- `tests/tools/unit_convertor.py` — MCP unit conversion server (stdio)

## Coverage

**Requirements:** None enforced in CI/config

## Test Types

**Unit Tests (`test_*.py` files):**
- Scope: Single class or function in isolation
- Dependencies: Mocked via `MagicMock`/`AsyncMock`/`FakeToolMapping`
- Key packages: `src/multimcp/retrieval/`, `src/multimcp/utils/`, `src/multimcp/adapters/`
- Pattern: **Direct pipeline injection** — construct `RetrievalPipeline` directly with dependencies passed in; no app-level startup
- Example: `tests/test_retrieval_pipeline.py`, `tests/test_bmx_retriever.py`, `tests/test_rrf_fusion.py`

**Integration Tests (`proxy_test.py`, `lifecycle_test.py`):**
- Scope: Multi-component flows — proxy + client manager + mock MCP servers
- Transport: In-memory via `create_connected_server_and_client_session`
- `lifecycle_test.py` starts a real subprocess (`python main.py start --transport sse`) and exercises the HTTP API
- Diagnostic output via `print()` with emoji prefixes

**End-to-End Tests (`e2e_test.py`):**
- Scope: Full system — real subprocess server + LangChain MCP client
- Covers: stdio mode, SSE mode, SSE backend clients
- LLM agent invocation is **optional** — gracefully skipped when `BASE_URL`/`OPENAI_API_KEY` env vars are absent
- Sleep-based readiness (`await asyncio.sleep(4)`) — no health-check polling yet
- Cleanup: `process.kill()` in `finally` block

## Phase 7 / Retrieval Tests — Direct Injection Pattern

Tests for `RetrievalPipeline` and its components do **not** construct the full app. Instead they:

1. Build a `tool_registry` dict directly using `_make_mapping()` / `_make_registry()` helpers
2. Instantiate `RetrievalPipeline` with explicit constructor injection:
   ```python
   pipeline = RetrievalPipeline(
       retriever=PassthroughRetriever(),        # or BMXFRetriever()
       session_manager=SessionStateManager(config),
       logger=NullLogger(),
       config=RetrievalConfig(enabled=True, rollout_stage="ga"),
       tool_registry=registry,
       telemetry_scanner=None,                  # optional
   )
   ```
3. Call `await pipeline.get_tools_for_list(session_id)` directly
4. Assert on returned `list[types.Tool]`

This pattern isolates retrieval logic completely from transport, config loading, and MCP server connections.

## Common Patterns

**Async Testing:**
```python
# asyncio_mode=auto means no decorator needed:
async def test_returns_all_connected_tools(self):
    tools = await pipeline.get_tools_for_list("session-1")
    assert len(tools) == 2

# Legacy tests still use explicit decorator (both work):
@pytest.mark.asyncio
async def test_proxy_call_tool(echo_server):
    ...
```

**Subprocess server + wait pattern (e2e):**
```python
process = await asyncio.create_subprocess_exec(
    "python", "main.py", "start", "--transport", "sse", "--config", "./examples/config/mcp.json",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
try:
    await asyncio.sleep(4)  # Wait for startup
    # ... test code ...
finally:
    process.kill()
    if process.stdout:
        await process.stdout.read()
    if process.stderr:
        await process.stderr.read()
```

**Error / isError testing:**
```python
result = await proxy.call_tool(MCPProxyServer._make_key(ECHO_SERVER_NAME, "echo"), {})
assert not result.isError
assert result.content == []
```

**Tool name set assertion:**
```python
tool_names = {tool.name for tool in tools.tools}
assert tool_names == {
    MCPProxyServer._make_key(SERVER1_NAME, test_tool_1.name),
    MCPProxyServer._make_key(SERVER2_NAME, test_tool_2.name),
}
```

**Diagnostic print in tests (acceptable):**
```python
print(f"\n✅ [{test_name}] Tools from proxy: {tool_names}")
print(f"🧪 Server list Before Add: {servers}")
```

---

*Testing analysis: 2025-07-10*
