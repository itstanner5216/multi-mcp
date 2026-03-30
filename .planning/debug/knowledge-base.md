# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## fix-test-failures-phase08 — 4 pre-existing test failures: weather tool missing, ProcessLookupError, kind not found
- **Date:** 2026-03-30
- **Error patterns:** weather__get_weather, AssertionError, ProcessLookupError, kind, _PRIVATE_RANGES, NotImplementedError, MultiServerMCPClient, langchain-mcp-adapters, SSRF, localhost, ConnectError, _validate_url
- **Root cause:** (1) multi_mcp.py run() always called _bootstrap_from_yaml() regardless of --config, loading 100+ servers so weather was never returned by retrieval; (2) _validate_url SSRF check was in _create_single_client() blocking localhost static configs; (3) missing "type":"sse" caused wrong transport auto-detection; (4) langchain-mcp-adapters 0.2.2 removed context manager + connect_to_server API; (5) _PRIVATE_RANGES removed from mcp_client.py breaking import; (6) k8s manifest port 8080 vs app port 8083 mismatch
- **Fix:** Gate _bootstrap_from_yaml on not self.settings.config; add _build_config_from_json_file(); move SSRF check to POST handler only; add "type":"sse" to mcp_sse.json; add conftest.py with MultiServerMCPClient compatibility shim; restore _PRIVATE_RANGES (fe80::/10, NOT loopback); fix k8s manifest to port 8083; add msc/mcp.json
- **Files changed:** src/multimcp/multi_mcp.py, src/multimcp/mcp_client.py, examples/config/mcp_sse.json, examples/k8s/multi-mcp.yaml, conftest.py, msc/mcp.json
---

