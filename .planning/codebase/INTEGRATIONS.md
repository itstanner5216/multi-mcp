# External Integrations

**Analysis Date:** 2025-01-30

## MCP Protocol (Core Integration)

Multi-MCP is itself an MCP server that proxies to multiple backend MCP servers. It speaks MCP on both sides.

**Outward-facing (multi-mcp as MCP server):**
- **stdio transport** — Default mode; `mcp.server.stdio.stdio_server` from `mcp==1.26.0`; used when invoked as a subprocess by Claude Desktop, Cursor, Zed, etc.
  - Implementation: `src/multimcp/multi_mcp.py` → `_run_stdio()`
- **SSE transport** — HTTP mode; `mcp.server.sse.SseServerTransport` mounted at `/sse` (GET) and `/messages/` (POST)
  - Implementation: `src/multimcp/multi_mcp.py` → `_run_sse()` via Starlette + uvicorn
  - Routes: `GET /sse`, `POST /messages/`, `GET /health`, `GET /mcp_tools`, `POST /mcp_control`

**Inward-facing (multi-mcp as MCP client to backends):**
All client logic lives in `src/multimcp/mcp_client.py` (`MCPClientManager`).

- **stdio** — Spawns backend MCP servers as subprocesses via `mcp.client.stdio.stdio_client`
  - Config shape: `{ "command": "python", "args": [...], "env": {...} }`
  - Security: command allowlist (`node`, `npx`, `uvx`, `python`, `python3`, `uv`, `docker`, `bash`, `sh`); overridable via `MULTI_MCP_ALLOWED_COMMANDS`; `PYTHONPATH`, `LD_PRELOAD` and 20+ other env vars are blocked
  - Examples: `examples/config/mcp.json` (weather + calculator as Python subprocesses)

- **SSE (HTTP)** — Connects to remote MCP servers exposing SSE endpoints via `mcp.client.sse.sse_client`
  - Config shape: `{ "url": "http://host/sse" }` or `{ "url": "...", "type": "sse" }`
  - SSRF protection: async DNS resolution; blocks all private/RFC-1918 IP ranges
  - Examples: `examples/config/mcp_sse.json` (mixed stdio + SSE backends)

- **Streamable HTTP** — Newer MCP transport via `mcp.client.streamable_http.streamable_http_client`
  - Config shape: `{ "url": "http://host/mcp", "type": "streamablehttp" }`
  - Used when `transport_type == "streamablehttp"` in `MCPClientManager._connect_url_server()`

## Backend MCP Server Examples (msc/mcp.json.bak)

These are the reference backend servers shipped in `msc/mcp.json.bak` that demonstrate the proxy's intended use with real third-party MCP servers:

| Server | Transport | Command | Auth Required | Trigger Keywords |
|---|---|---|---|---|
| `github` | stdio | `npx -y @modelcontextprotocol/server-github` | `GITHUB_PERSONAL_ACCESS_TOKEN` env var | github, repository, pr, issue, commit, branch |
| `brave-search` | stdio | `npx -y @modelcontextprotocol/server-brave-search` | `BRAVE_API_KEY` env var | search, web search, find, lookup |
| `context7` | stdio | `npx -y @upstash/context7-mcp` | None | documentation, docs, api reference, package |

These Node.js-based servers are run as subprocesses (`npx`), requiring Node.js 20+ in the Docker image.

## LangChain / LangGraph Adapter Layer

Multi-mcp exposes its aggregated tools to the LangChain ecosystem via `langchain-mcp-adapters==0.2.2`.

**Pattern:** `MultiServerMCPClient` from `langchain_mcp_adapters.client` connects to multi-mcp (either via stdio subprocess or SSE URL) and wraps MCP tools as LangChain `BaseTool` instances.

**Example:** `examples/connect_langgraph_client.py`
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

async with MultiServerMCPClient() as client:
    await client.connect_to_server("multi-mcp", command="python", args=["./main.py"])
    tools = client.get_tools()
    agent = create_react_agent(model, tools)
```

**Supported connection modes to multi-mcp from LangChain:**
- `command=` + `args=` — stdio subprocess
- `transport="sse"` + `url="http://127.0.0.1:8080/sse"` — SSE HTTP

## AI Tool Config Adapters (auto-registration)

Multi-mcp can auto-register itself into the MCP config files of 16 AI coding tools via `src/multimcp/adapters/`. Each adapter reads and writes the tool's native config format.

**Adapter Registry:** `src/multimcp/adapters/registry.py` → `AdapterRegistry`
**Base class:** `src/multimcp/adapters/base.py` → `MCPConfigAdapter`

| Adapter | Tool | Config Format | Platforms |
|---|---|---|---|
| `AntigravityAdapter` | Antigravity | — | — |
| `ClaudeDesktopAdapter` | Anthropic Claude Desktop | JSON | macOS, Windows |
| `ClineAdapter` | Cline (VS Code) | JSON | All |
| `CodexCLIAdapter` | OpenAI Codex CLI | JSON | All |
| `CodexDesktopAdapter` | OpenAI Codex Desktop | JSON | macOS, Windows |
| `ContinueDevAdapter` | Continue.dev | JSON/YAML | All |
| `GeminiCLIAdapter` | Google Gemini CLI | JSON | All |
| `GitHubCopilotAdapter` | GitHub Copilot | JSON | All |
| `GptmeAdapter` | gptme | TOML | All |
| `JetBrainsAdapter` | JetBrains IDEs | JSON | All |
| `OpenClawAdapter` | OpenClaw | — | — |
| `OpenCodeAdapter` | OpenCode | JSON | All |
| `RaycastAdapter` | Raycast | JSON | macOS |
| `RooCodeAdapter` | Roo Code | JSON | All |
| `WarpAdapter` | Warp terminal | JSON | macOS, Linux |
| `ZedAdapter` | Zed editor | JSON | macOS, Linux |

Config paths and discovery logic are defined per-adapter in `src/multimcp/adapters/tools/`.

## Configuration Sources (Server Discovery)

Multi-mcp discovers backend servers from multiple sources at startup:

1. **JSON config file** — Passed via `--config mcp.json` CLI arg or `MULTI_MCP_CONFIG`; format matches Claude Desktop's `mcpServers` schema (`src/multimcp/multi_mcp.py` → `load_mcp_config()`)
2. **Claude Desktop configs** — Auto-scanned from platform-appropriate paths via `ClaudeDesktopAdapter` → `_scan_claude_desktop_configs()`
3. **Claude Code plugins** — Scanned from Claude Code plugin directories → `_scan_claude_plugins()`
4. **YAML state file** — Persisted at `~/.config/multi-mcp/servers.yaml`; merged with JSON config on subsequent starts; managed by `src/multimcp/yaml_config.py`

## Authentication

**API Key Auth (optional):**
- Set `MULTI_MCP_API_KEY` env var to enable
- SSE transport: validates `Authorization: Bearer <token>` header using `hmac.compare_digest` (timing-safe)
- Also checks `X-API-Key` header as alternative
- Implementation: `src/multimcp/multi_mcp.py` → `_auth_wrapper()` / `_validate_api_key()`
- No auth provider — custom implementation only

## Data Storage

**Databases:** None — no database dependency

**File Storage (local only):**
- YAML config: `~/.config/multi-mcp/servers.yaml` — persistent server registry with tool discovery cache
- JSON config (read-only input): user-provided file path or `mcp.json` in working directory

**Caching:** In-memory only — `src/multimcp/cache_manager.py` manages tool discovery results in process memory; no Redis or external cache

## Monitoring & Observability

**Health Endpoint:** `GET /health` (SSE mode only) — returns JSON with connected/pending server counts
- Implementation: `src/multimcp/multi_mcp.py` → `handle_health()`

**Error Tracking:** None — no Sentry, Datadog, or similar integration

**Logs:** `loguru==0.7.3` to stdout/stderr; log level controlled via `MULTI_MCP_LOG_LEVEL`

## CI/CD & Deployment

**Container:**
- `Dockerfile` — Multi-stage uv + Python 3.12 + Node.js 20; exposes no EXPOSE directive; default CMD runs SSE mode on `0.0.0.0`
- Build: `make docker-build` (`docker build -t multi-mcp .`)
- Run: `make docker-run` (`docker run -p 8085:8085 multi-mcp`)

**Kubernetes:**
- Manifests: `examples/k8s/multi-mcp.yaml`
- Deployment: 1 replica, image `multi-mcp:latest`, port 8080
- Service: `NodePort` on port 30080
- No Helm chart; no ConfigMap/Secret management defined in manifests

**CI Pipeline:** None detected (no `.github/workflows/`, no CircleCI, no GitLab CI)

**Hosting:** Self-hosted (Docker / Kubernetes) — no cloud-specific SDK or PaaS integration

## Webhooks & Callbacks

**Incoming:** None — multi-mcp does not receive webhooks

**Outgoing:** None — multi-mcp does not send webhooks

## Environment Configuration

**Required env vars (for full functionality):**
- `MULTI_MCP_API_KEY` — Optional; enables bearer token auth on SSE endpoints
- `MULTI_MCP_TRANSPORT` — `stdio` (default) or `sse`
- `MULTI_MCP_HOST` / `MULTI_MCP_PORT` — SSE bind address (defaults: `127.0.0.1:8085`)
- `MULTI_MCP_PROFILE` — Optional named tool filter profile
- `MULTI_MCP_ALLOWED_COMMANDS` — Comma-separated subprocess command allowlist
- Backend server secrets (passed through to subprocess env): `GITHUB_PERSONAL_ACCESS_TOKEN`, `BRAVE_API_KEY`, etc. — these are defined in the MCP JSON config under each server's `env` block and forwarded to the subprocess (after stripping protected vars)

**Secrets location:** Environment variables only — no secrets manager integration

---

*Integration audit: 2025-01-30*
