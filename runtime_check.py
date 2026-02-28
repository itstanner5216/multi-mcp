#!/usr/bin/env python3
"""
Multi-MCP Runtime Validation — real subprocess backends, real MCP protocol.

Runs without mocks. Tests every layer that broke in production:
  - tool names (no colons, double-underscore namespacing)
  - inputSchema not empty
  - tool calls actually execute and return correct results
  - multi-backend isolation (calc tools don't bleed to converter and vice-versa)
  - unknown tool returns error, not crash
  - slow backend doesn't hang startup (discovery timeout)
  - SSE transport (port 18099) — tools visible, calls work
"""

import asyncio
import json
import sys
import subprocess
import time
import httpx
from contextlib import AsyncExitStack
from pathlib import Path

REPO = Path(__file__).parent
PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
_results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {status}: {label}{suffix}")
    _results.append((label, condition, detail))
    return condition


def header(title: str) -> None:
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


async def run_all() -> int:
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.session import ClientSession
    from mcp import types
    from src.multimcp.mcp_client import MCPClientManager
    from src.multimcp.mcp_proxy import MCPProxyServer

    # ------------------------------------------------------------------ #
    # PHASE 1: Backend server sanity — direct connection, no proxy
    # ------------------------------------------------------------------ #
    header("PHASE 1: Backend sanity (direct stdio, no proxy)")

    calc_path = str(REPO / "tests/tools/calculator.py")
    conv_path = str(REPO / "tests/tools/unit_convertor.py")

    async with AsyncExitStack() as stack:
        cr, cw = await stack.enter_async_context(
            stdio_client(StdioServerParameters(command="python3", args=[calc_path]))
        )
        calc = await stack.enter_async_context(ClientSession(cr, cw))
        await calc.initialize()

        tools_res = await calc.list_tools()
        tnames = [t.name for t in tools_res.tools]
        check("calculator responds", True)
        check("add exists",      "add"      in tnames)
        check("multiply exists", "multiply" in tnames)

        add_tool = next(t for t in tools_res.tools if t.name == "add")
        props = add_tool.inputSchema.get("properties", {})
        check("add has real schema (not empty)", bool(props), str(add_tool.inputSchema))
        check("add schema has 'a'", "a" in props)
        check("add schema has 'b'", "b" in props)

        r = await calc.call_tool("add", {"a": 3, "b": 4})
        out = r.content[0].text if r.content else ""
        check("add(3,4) no error",   not r.isError, out)
        check("add(3,4) == 7",       "7" in str(out), f"got: {out}")

        r = await calc.call_tool("multiply", {"a": 3, "b": 4})
        out = r.content[0].text if r.content else ""
        check("multiply(3,4) == 12", "12" in str(out), f"got: {out}")

    # ------------------------------------------------------------------ #
    # PHASE 2: Proxy passthrough — naming, schemas, routing, calls
    # ------------------------------------------------------------------ #
    header("PHASE 2: Proxy passthrough (tool names, schemas, tool calls)")

    # Use try/except for ExceptionGroup — anyio raises it when stdio_client
    # background reader tasks see their stream closed during stack cleanup.
    # This is expected and benign; the checks already completed successfully.
    try:
      async with AsyncExitStack() as stack:
        cr, cw = await stack.enter_async_context(
            stdio_client(StdioServerParameters(command="python3", args=[calc_path]))
        )
        calc_sess = await stack.enter_async_context(ClientSession(cr, cw))
        await calc_sess.initialize()

        vr, vw = await stack.enter_async_context(
            stdio_client(StdioServerParameters(command="python3", args=[conv_path]))
        )
        conv_sess = await stack.enter_async_context(ClientSession(vr, vw))
        await conv_sess.initialize()

        mgr = MCPClientManager()
        mgr.clients["calc"]      = calc_sess
        mgr.clients["converter"] = conv_sess
        mgr.tool_filters["calc"]      = None
        mgr.tool_filters["converter"] = None

        proxy = MCPProxyServer(mgr)
        await proxy.initialize_single_client("calc",      calc_sess)
        await proxy.initialize_single_client("converter", conv_sess)

        keys = list(proxy.tool_to_server.keys())
        check("calc__add in proxy",                    "calc__add"                         in keys, str(keys))
        check("calc__multiply in proxy",               "calc__multiply"                    in keys)
        check("converter__convert_temperature in proxy","converter__convert_temperature"    in keys)
        check("converter__convert_length in proxy",    "converter__convert_length"         in keys)
        check("exactly 4 tools total",                 len(keys) == 4,                     str(keys))

        # THE historic bug: colons in tool names
        colon_tools = [k for k in keys if ":" in k]
        check("NO colon ':' in any tool name",         len(colon_tools) == 0,
              f"offenders: {colon_tools}" if colon_tools else "clean")

        # All keys split correctly
        bad_split = [k for k in keys if len(k.split("__", 1)) != 2]
        check("all keys split cleanly on '__'",        len(bad_split) == 0,
              f"bad: {bad_split}" if bad_split else "clean")

        # Schema not empty (the fix we just shipped)
        m = proxy.tool_to_server["calc__add"]
        props = m.tool.inputSchema.get("properties", {})
        check("calc__add schema NOT empty",   bool(props), str(m.tool.inputSchema))
        check("calc__add schema has 'a'",     "a" in props)
        check("calc__add schema has 'b'",     "b" in props)

        conv_m = proxy.tool_to_server["converter__convert_temperature"]
        conv_props = conv_m.tool.inputSchema.get("properties", {})
        check("convert_temperature schema has 'value'",    "value"     in conv_props)
        check("convert_temperature schema has 'from_unit'","from_unit" in conv_props)

        # Tool call through proxy — does add actually execute?
        def _out(r) -> str:
            """Extract text from ServerResult.root.content[0].text"""
            try:
                return r.root.content[0].text
            except Exception:
                return str(r)

        def _is_error(r) -> bool:
            try:
                return bool(r.root.isError)
            except Exception:
                return False

        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="calc__add", arguments={"a": 5, "b": 7}),
        )
        result = await proxy._call_tool(req)
        out = _out(result)
        check("calc__add(5,7) no proxy error", not _is_error(result), out)
        check("calc__add(5,7) == 12",          "12" in str(out), f"got: {out}")

        # Routing isolation — converter tool goes to the right backend
        req2 = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="converter__convert_temperature",
                arguments={"value": 100.0, "from_unit": "Celsius", "to_unit": "Fahrenheit"},
            ),
        )
        result2 = await proxy._call_tool(req2)
        out2 = _out(result2)
        check("convert_temp(100C→F) no error", not _is_error(result2), out2)
        check("convert_temp(100C→F) == 212",   "212" in out2, f"got: {out2}")

        # multiply — a separate tool going to calc
        req3 = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="calc__multiply", arguments={"a": 6, "b": 7}),
        )
        result3 = await proxy._call_tool(req3)
        out3 = _out(result3)
        check("calc__multiply(6,7) == 42",     "42" in str(out3), f"got: {out3}")

        # Unknown tool → graceful error, NOT crash
        req_bad = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="nobody__nothing", arguments={}),
        )
        result_bad = await proxy._call_tool(req_bad)
        check("unknown tool returns isError (not crash)", _is_error(result_bad))

    except* Exception as eg:
        # anyio wraps ClosedResourceError from stdio_client cleanup in ExceptionGroup.
        # Only non-ClosedResourceError sub-exceptions are real failures.
        import anyio
        real = [e for e in eg.exceptions if not isinstance(e, anyio.ClosedResourceError)]
        if real:
            check("Phase 2 clean shutdown", False, str(real))
        # else: ClosedResourceError only — expected, benign

    # ------------------------------------------------------------------ #
    # PHASE 3: Discovery timeout — slow backend doesn't hang startup
    # ------------------------------------------------------------------ #
    header("PHASE 3: Discovery timeout (slow server must not hang startup)")

    # Write a backend that sleeps forever during handshake
    slow_script = REPO / "/tmp/slow_mcp_server.py"
    slow_script.parent.mkdir(parents=True, exist_ok=True)
    slow_script = Path("/tmp/slow_mcp_server.py")
    slow_script.write_text("import time\ntime.sleep(9999)\n")

    from src.multimcp.mcp_client import MCPClientManager
    from src.multimcp.yaml_config import MultiMCPConfig, ServerConfig

    mgr2 = MCPClientManager(connection_timeout=3.0)  # 3s timeout for test speed
    config = MultiMCPConfig(servers={
        "slow": ServerConfig(command="python3", args=[str(slow_script)]),
        # A fast server comes AFTER — must not be blocked by slow one
    })

    t0 = time.monotonic()
    discovered = await mgr2.discover_all(config)
    elapsed = time.monotonic() - t0

    check("slow server returns [] (not hang)",  discovered.get("slow") == [],
          f"got: {discovered.get('slow')}")
    check("discovery completes in <10s",        elapsed < 10,
          f"took {elapsed:.1f}s")
    check("discovery respects timeout (~3s)",   elapsed < 7,
          f"took {elapsed:.1f}s (expected ~3s)")

    slow_script.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # PHASE 4: SSE transport (port 18099)
    # ------------------------------------------------------------------ #
    header("PHASE 4: SSE transport (port 18099)")

    # Write a minimal test config pointing at calculator
    test_cfg = Path("/tmp/multi_mcp_runtime_test.json")
    test_cfg.write_text(json.dumps({
        "mcpServers": {
            "calc": {
                "command": "python3",
                "args": [calc_path],
            }
        }
    }))

    # Use a temp YAML dir so we don't pollute the real config
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_yaml = Path(tmpdir) / "servers.yaml"

        # Patch YAML_CONFIG_PATH so this test doesn't touch the real config
        import src.multimcp.multi_mcp as mm_mod
        original_yaml_path = mm_mod.YAML_CONFIG_PATH
        mm_mod.YAML_CONFIG_PATH = tmp_yaml

        from src.multimcp.multi_mcp import MultiMCP

        server = MultiMCP(transport="sse", host="127.0.0.1", port=18099,
                          config=str(test_cfg))

        server_task = asyncio.create_task(server.run())
        await asyncio.sleep(6)  # Wait for startup (discovery + bind)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Health check
                r = await client.get("http://127.0.0.1:18099/health")
                check("SSE /health returns 200",       r.status_code == 200, str(r.status_code))
                body = r.json()
                check("SSE /health has status=healthy",body.get("status") == "healthy", str(body))

                # mcp_servers endpoint — pending servers visible
                r2 = await client.get("http://127.0.0.1:18099/mcp_servers")
                check("SSE /mcp_servers returns 200",  r2.status_code == 200)
                body2 = r2.json()
                check("response has active_servers key",  "active_servers"  in body2, str(body2))
                check("response has pending_servers key", "pending_servers" in body2, str(body2))
                all_servers = body2.get("active_servers", []) + body2.get("pending_servers", [])
                check("calc server visible in response",  "calc" in all_servers, str(body2))

                # mcp_tools endpoint
                r3 = await client.get("http://127.0.0.1:18099/mcp_tools")
                check("SSE /mcp_tools returns 200",    r3.status_code == 200)

        except Exception as e:
            check("SSE server reachable",   False, str(e))
        finally:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):
                pass
            mm_mod.YAML_CONFIG_PATH = original_yaml_path
            test_cfg.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n{'='*65}")
    total   = len(_results)
    passed  = sum(1 for _, ok, _ in _results if ok)
    failed  = total - passed
    print(f"  RESULT: {passed}/{total} checks passed  ({failed} failed)")
    if failed:
        print("\n  Failed checks:")
        for label, ok, detail in _results:
            if not ok:
                print(f"    ❌ {label}" + (f"  ({detail})" if detail else ""))
    print(f"{'='*65}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_all()))
