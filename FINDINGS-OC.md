# FINDINGS-OC.md — Cross-Agent Issues Found During OC Final Pass

## SSE Transport Error (Outside OC Scope)

**Severity:** Medium — SSE transport non-functional in dev environment  
**Location:** MCP SDK SSE transport layer (likely `starlette_sse.py` or Starlette integration)  
**Symptom:** `TypeError: 'NoneType' object is not callable` when connecting to `/sse` endpoint  
**Context:** Server starts successfully on port 8087 (Uvicorn confirms binding), but SSE endpoint fails on first connection attempt.  
**Impact:** SSE-based clients cannot connect in dev environment. Stdio transport works fine.  
**Root Cause Hypothesis:** The MCP SDK's SSE implementation expects middleware/config that isn't present when no upstream MCP servers are connected. Without `msc/mcp.json` config, there are no upstream servers to proxy, which may cause a NoneType in the SSE handler.  
**Recommendation:** CLI agent should investigate the SSE handler initialization path in `mcp_proxy.py` / `multi_mcp.py` to ensure the SSE endpoint gracefully handles the case where no upstream MCP servers are configured.

## Dockerfile — Missing `msc/mcp.json` Config

**Severity:** Low — Fixed by OC agent  
**Location:** `Dockerfile` line 21-22  
**Symptom:** `COPY ./msc/mcp.json /app/mcp.json` fails because file doesn't exist in repo  
**Fix Applied:** Changed from `COPY` to conditional `RUN test -f ... || true` so Docker builds succeed whether or not the config file is present.  
**Impact on Other Agents:** None — the fix is backwards-compatible. If `msc/mcp.json` exists, it gets copied. If not, the build continues.

## No Other Cross-Agent Issues Found

All retrieval package files, yaml_config.py, cli.py, mcp_trigger_manager.py, and infrastructure files were audited line-by-line. No issues requiring changes to files outside OC scope were identified.
