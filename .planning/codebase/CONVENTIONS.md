# Coding Conventions

**Analysis Date:** 2025-07-10

## Naming Patterns

**Files:**
- Modules use `snake_case.py`: `mcp_proxy.py`, `mcp_client.py`, `yaml_config.py`
- Test files prefixed with `test_`: `test_retrieval_pipeline.py`, `test_bmx_retriever.py`
- Legacy integration tests without prefix: `proxy_test.py`, `e2e_test.py`, `lifecycle_test.py`

**Classes:**
- `PascalCase`: `MCPProxyServer`, `MCPClientManager`, `MultiMCP`, `RetrievalPipeline`, `BMXFRetriever`
- Dataclass models also `PascalCase`: `ToolMapping`, `ScoredTool`, `RetrievalContext`, `RetrievalConfig`

**Functions & Methods:**
- `snake_case` for all functions and methods: `get_logger`, `load_config`, `rebuild_index`
- Private helpers prefixed with `_`: `_make_key`, `_split_key`, `_extract_conv_terms`, `_check_auth`
- Factory class methods named `create`: `MCPProxyServer.create(client_manager)`

**Variables:**
- `snake_case` for all variables and instance attributes
- Constants `UPPER_SNAKE_CASE`: `BASE_LOGGER_NAMESPACE`, `DEFAULT_ALLOWED_COMMANDS`, `RRF_K`

**Type Annotations:**
- All public function signatures must have type annotations
- Use `Optional[T]` (not `T | None`) for Python 3.10 compatibility
  ```python
  # Correct
  self.proxy: Optional[MCPProxyServer] = None
  def _check_auth(self, request: Request) -> Optional[JSONResponse]: ...
  
  # Forbidden (breaks 3.10)
  self.proxy: MCPProxyServer | None = None
  ```
- Import from `typing`: `from typing import Optional, Literal, Any, Dict`
- Use `Literal` for string enums: `Literal["stdio", "sse", "http", "streamablehttp"]`

## Code Style

**Formatting:**
- No formatter config detected (no `.prettierrc`, `biome.json`, `ruff.toml`); follow PEP 8
- 4-space indentation throughout

**Linting:**
- `pyrightconfig.json` present — pyright is the type checker
- `filterwarnings = ["ignore::pydantic.warnings.PydanticDeprecatedSince20"]` in pytest config suppresses Pydantic v1 compat warnings

## Import Organization

**Order (PEP 8):**
1. `from __future__ import annotations` (when needed for forward references)
2. Standard library (`asyncio`, `pathlib`, `typing`, `dataclasses`)
3. Third-party (`mcp`, `pydantic`, `loguru`, `anyio`)
4. Local (`from src.multimcp...`, `from src.utils.logger...`)

**Path Aliases:**
- No path aliases — imports use full `src.*` prefix: `from src.multimcp.mcp_proxy import MCPProxyServer`
- `pythonpath = ["."]` in pytest config enables root-relative imports

**Forward References:**
- Use `TYPE_CHECKING` guard + string annotations to avoid circular imports:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from src.multimcp.retrieval.pipeline import RetrievalPipeline
  # Then use: Optional["RetrievalPipeline"]
  ```

## Logging

**Framework:** loguru (`src/utils/logger.py`)

**Getting a logger — always use `get_logger()`:**
```python
from src.utils.logger import get_logger

self.logger = get_logger("multi_mcp.ProxyServer")
# Creates logger.bind(module="multi_mcp.multi_mcp.ProxyServer")
```

**Log level with emoji prefix convention (required):**
```python
self.logger.info(f"✅ Always-on server '{server_name}' connected")
self.logger.warning(f"⚠️ Profile '{profile_name}' not found in config")
self.logger.error(f"❌ Background task '{task.get_name()}' failed: {exc}")
self.logger.info(f"🔍 Found {len(new_servers)} new server(s)")
```

**Emoji conventions:**
- `✅` — success / completed operations
- `❌` — errors / failures
- `⚠️` — warnings / degraded state
- `🔍` / `🔎` — discovery / search
- `🛑` — shutdown / stopped
- `📝` — writes / saves

**Never use `print()` in production code** (tests may use it for diagnostic output).

## Async Patterns

**Runtime:** `anyio` preferred for top-level async operations; `asyncio` used directly for locks, subprocesses, and `asyncio.create_subprocess_exec`

**Resource management — always `async with` via `AsyncExitStack`:**
```python
from contextlib import AsyncExitStack

async with AsyncExitStack() as stack:
    session = await stack.enter_async_context(some_client())
```

**Client lifecycles — inject via `MCPClientManager`, do not create raw sessions inline**

**No blocking I/O in async functions.** File reads must use `asyncio.to_thread()` or pathlib in sync context only.

## Pydantic v2 Patterns

**Models use `BaseModel` from pydantic v2:**
```python
from pydantic import BaseModel, Field, ValidationError

class ServerConfig(BaseModel):
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    tools: dict[str, ToolEntry] = Field(default_factory=dict)
```

**Serialization:** use `.model_dump()` and `.model_validate()` (not deprecated `.dict()` / `.parse_obj()`):
```python
server_dict = server_config.model_dump(exclude_none=True)
config = MultiMCPConfig.model_validate(raw)
```

**Data classes** (`@dataclass`) used for internal pipeline models (not user-facing config):
- `RetrievalContext`, `ScoredTool`, `ToolMapping`, `ToolDoc` are all `@dataclass`
- Pydantic `BaseModel` reserved for config that needs validation + YAML/JSON I/O

## Error Handling

**Rules:**
1. Every `except` block must either **log** the error or **re-raise** — no silent swallowing
2. No bare `except:` — always `except Exception as e:` at minimum
3. For per-client failures, log and continue (don't kill the whole proxy):
   ```python
   try:
       await client.initialize()
   except Exception as e:
       self.logger.warning(f"⚠️ Failed to connect '{name}': {e}")
       # Continue — don't propagate
   ```
4. For MCP protocol errors, raise `McpError` with `ErrorData`:
   ```python
   from mcp.shared.exceptions import McpError
   from mcp.types import ErrorData, INTERNAL_ERROR
   raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed: {e}"))
   ```
5. Config load failures return a safe default (empty `MultiMCPConfig()`) rather than propagating

## Tool Namespacing

**Double-underscore separator (`__`) is canonical:**
```python
# Creating a namespaced key
MCPProxyServer._make_key("github", "search_repositories")
# → "github__search_repositories"

# Splitting back
server_name, tool_name = MCPProxyServer._split_key("github__search_repositories")

# Keys stored in
self.tool_to_server: dict[str, ToolMapping] = {}
```

**Server names must not contain `__`** — validated at registration:
```python
if "__" in name:
    raise ValueError(f"Server name '{name}' cannot contain '__' separator")
```

## File Operations

**Always use `pathlib.Path`** — never raw string concatenation for paths:
```python
from pathlib import Path

yaml_path = Path(yaml_path)
path.parent.mkdir(parents=True, exist_ok=True)
config_path = Path(appdata) / "Claude" / "claude_desktop_config.json"
```

## HTTP Clients

**Use `httpx` (async)** — `requests` is not used in this codebase. The `httpx-sse` package handles SSE client connections.

## Docstrings

**Required on all public classes and methods:**
```python
class MCPProxyServer(server.Server):
    """An MCP Proxy Server that forwards requests to remote MCP servers."""

    @classmethod
    async def create(cls, client_manager: MCPClientManager) -> "MCPProxyServer":
        """Factory method to create and initialize the proxy with clients."""
```

**Module-level docstrings** on all files under `src/multimcp/retrieval/`:
```python
"""RetrievalPipeline — single entry point for tool filtering and ranking."""
```

## Module Design

**Exports:**
- No `__all__` enforcement; exports are implicit via public names
- No barrel `__init__.py` re-exports in most packages (direct imports used)

**Optional imports with try/except** for optional pipeline components:
```python
try:
    from .fusion import weighted_rrf as _weighted_rrf
    _HAS_FUSION = True
except ImportError:
    _HAS_FUSION = False
```

---

*Convention analysis: 2025-07-10*
