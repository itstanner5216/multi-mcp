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

## RetrievalConfig Wiring — Hardcoded `enabled=False` Ignores YAML Config

**Severity:** High — Retrieval pipeline can never be enabled via configuration  
**Location:** `multi_mcp.py` line 373  
**Symptom:** `RetrievalConfig(enabled=False)` is hardcoded when creating the `RetrievalPipeline`. The YAML config's `retrieval:` section (`RetrievalSettings` in `yaml_config.py`) is read but never used to construct the `RetrievalConfig`.  
**Impact:** Users who set `retrieval.enabled: true` in their YAML config will have no effect — the pipeline always runs in disabled/passthrough mode.  
**Root Cause:** The wiring in `multi_mcp.py` constructs `RetrievalConfig(enabled=False)` directly instead of converting from the loaded `MultiMCPConfig.retrieval` (`RetrievalSettings`) to `RetrievalConfig`.  
**Recommendation:** CLI agent should update `multi_mcp.py` to read from `config.retrieval` (the `RetrievalSettings` Pydantic model) and convert it to `RetrievalConfig`:  
```python
# In multi_mcp.py, replace:
#   retrieval_config = RetrievalConfig(enabled=False)
# With:
#   yaml_retrieval = config.retrieval  # RetrievalSettings from yaml_config
#   retrieval_config = RetrievalConfig(
#       enabled=yaml_retrieval.enabled,
#       top_k=yaml_retrieval.top_k,
#       full_description_count=yaml_retrieval.full_description_count,
#       anchor_tools=yaml_retrieval.anchor_tools,
#   )
```

## No Other Cross-Agent Issues Found

All retrieval package files, yaml_config.py, cli.py, mcp_trigger_manager.py, and infrastructure files were audited line-by-line. The only issue requiring changes to files outside OC scope is the RetrievalConfig wiring above.
