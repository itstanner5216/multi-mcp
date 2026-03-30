# Technology Stack

**Analysis Date:** 2025-01-30

## Languages

**Primary:**
- Python 3.10+ — All application code, enforced via `requires-python = ">=3.10"` in `pyproject.toml`

**Secondary:**
- None (Node.js is a runtime dependency inside Docker for backend MCP servers like GitHub/Brave, not application code)

## Runtime

**Environment:**
- Python 3.12 (Docker image: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` per `Dockerfile`)
- Node.js 20.x — installed in Docker image via NodeSource for running `npx`-based MCP backend servers

**Package Manager:**
- `uv` — Used for venv creation, installs, and running (`uv run main.py start` per `Makefile`)
- Lockfile: `uv.lock` (present and committed)
- Install command: `uv pip install -r requirements.txt`

## Frameworks

**Core:**
- `starlette==0.52.1` — ASGI web framework powering the SSE transport HTTP layer; routes `/sse`, `/messages/`, `/health`, `/mcp_tools`, `/mcp_control`
- `anyio==4.13.0` — Async concurrency primitives; used for task groups and structured concurrency alongside `asyncio`
- `mcp==1.26.0` — Official MCP Python SDK; provides `stdio_server`, `SseServerTransport`, `ClientSession`, `stdio_client`, `sse_client`, `streamable_http_client`

**HTTP Server:**
- `uvicorn==0.42.0` — ASGI server serving the Starlette app in SSE mode; configured in `src/multimcp/multi_mcp.py`

**Settings:**
- `pydantic==2.12.5` — Data validation and modelling; `BaseModel` used throughout for config models
- `pydantic-settings==2.13.1` — `BaseSettings` with `MULTI_MCP_` env prefix for `MCPSettings` in `src/multimcp/multi_mcp.py`
- `pydantic-core==2.41.5` — Pydantic v2 Rust core

**Config Serialization:**
- `pyyaml==6.0.3` — YAML config reading/writing (`src/multimcp/yaml_config.py`)
- `tomli_w==1.2.0` — TOML config writing for adapter tool configs

**Logging & Display:**
- `loguru==0.7.3` — Structured logging via `src/utils/logger.py`; used everywhere via `get_logger()`
- `rich==14.3.3` — Terminal output formatting (used in CLI and display utilities)

**Networking:**
- `httpx==0.28.1` — HTTP client used by MCP SSE client internals
- `httpx-sse==0.4.3` — SSE streaming support for `httpx`, required by `mcp.client.sse`
- `sse-starlette==3.3.3` — SSE response support (pulled in transitively)

**LangChain Integration:**
- `langchain-mcp-adapters==0.2.2` — `MultiServerMCPClient` adapter bridging MCP tools to LangChain tool interface
- `langchain-core==1.2.22` — LangChain base abstractions (tool interface, runnable, etc.)

**Testing:**
- `pytest>=9.0.2` — Test runner; config in `pyproject.toml` under `[tool.pytest.ini_options]`
- `pytest-asyncio>=1.3.0` — Async test support; `asyncio_mode = "auto"` set globally
- `pytest-asyncio==1.3.0` — (exact pinned in `requirements.txt`)

**Optional Test Dependencies (declared in `pyproject.toml`):**
- `langgraph` — For LangGraph agent integration tests
- `langchain-openai` — OpenAI LLM backend for integration tests
- `python-dotenv==1.2.2` — `.env` loading in tests/examples

## Key Dependencies

**Critical:**
- `mcp==1.26.0` — Core protocol SDK; all proxy logic depends on `mcp.server`, `mcp.client`, and `mcp.types`
- `pydantic>=2.0.0` — All config models use Pydantic v2; downgrading to v1 would break everything
- `starlette` (unpinned in `pyproject.toml`, pinned `0.52.1` in `requirements.txt`) — SSE transport HTTP backbone
- `anyio==4.13.0` — Used for structured concurrency; must be compatible with `mcp` SDK version

**Infrastructure:**
- `uvicorn==0.42.0` — Production ASGI server for SSE mode
- `langchain-mcp-adapters==0.2.2` — Consumer-facing LangChain compatibility layer
- `pyyaml==6.0.3` — YAML config (servers.yaml) is the primary persistent config format
- `loguru==0.7.3` — All log output; replacing this would require changes across all modules

## Configuration

**Environment:**
- All settings use `MULTI_MCP_` prefix (via `pydantic-settings` env prefix in `src/multimcp/multi_mcp.py`)
- Key env vars:
  - `MULTI_MCP_HOST` — Bind host (default: `127.0.0.1`)
  - `MULTI_MCP_PORT` — Bind port (default: `8085`)
  - `MULTI_MCP_TRANSPORT` — `stdio` or `sse` (default: `stdio`)
  - `MULTI_MCP_API_KEY` — Optional bearer token authentication
  - `MULTI_MCP_PROFILE` — Named tool filter profile
  - `MULTI_MCP_LOG_LEVEL` — `DEBUG|INFO|WARNING|ERROR|CRITICAL`
  - `MULTI_MCP_DEBUG` — Expose exception details in responses
  - `MULTI_MCP_ALLOWED_COMMANDS` — Comma-separated subprocess allowlist (default: `node,npx,uvx,python,python3,uv,docker,bash,sh`)
- `.env` file loading: supported via `python-dotenv` in test/example contexts

**Build:**
- `pyproject.toml` — Project metadata and abstract dependency declarations
- `requirements.txt` — Pinned lockfile for production installs
- `uv.lock` — `uv`-native lockfile

## Platform Requirements

**Development:**
- Python ≥ 3.10
- `uv` package manager
- Node.js 20+ (optional, for running `npx`-based backend servers locally)
- Run dev server: `uv run main.py start`

**Production:**
- Docker: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` base image with Node.js 20.x
- Kubernetes: manifests in `examples/k8s/multi-mcp.yaml` (Deployment + NodePort Service on port 8080/30080)
- Entry command: `python main.py start --transport sse --config mcp.json --host 0.0.0.0`

---

*Stack analysis: 2025-01-30*
