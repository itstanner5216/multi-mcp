
## Server-Side Streamable HTTP Transport

**Problem:** Claude.ai (web) uses the newer MCP Streamable HTTP transport (single POST endpoint), 
but multi-mcp only exposes the old SSE transport (GET `/sse` + POST `/messages/`). 
Claude.ai connects, gets the SSE event stream, then POSTs back to `/sse` expecting JSON-RPC — fails.

**Client-side already works:** `mcp_client.py` uses `streamable_http_client` for connecting TO backends.

**What's needed:** Add `StreamableHTTPServerTransport` from `mcp.server.streamable_http` as a 
server-facing transport alongside SSE. Mount at `/mcp` (or dual-purpose `/sse`). 
The library (mcp 1.26.0) already includes it — just needs wiring into `multi_mcp.py` routes + 
profile support.

**Starlette integration:** `StreamableHTTPServerTransport.handle_request(scope, receive, send)` 
is ASGI-compatible — can be a Starlette route handler directly.

**Caddy route already exists:** `/mcp/*` → `host.docker.internal:8085` (strip prefix).

**Claude.ai URL would be:** `https://cohort-xero.duckdns.org/mcp/mcp` (or adjust Caddy route).
