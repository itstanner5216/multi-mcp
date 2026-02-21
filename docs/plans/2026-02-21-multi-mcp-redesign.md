# Multi-MCP Proxy Redesign
**Date:** 2026-02-21
**Status:** Design Approved — ready for implementation
**Scope:** Proxy only. Semantic router is a separate future project.

---

## Goal

A system-wide MCP proxy that is genuinely better than anything currently on GitHub:
- Single endpoint for all AI tools (Claude Code, Codex, OpenCode, Antigravity, Copilot)
- Lazily loads backend servers — connects only when a tool is actually called
- Tool-level enable/disable with zero friction — edit one YAML file
- Works out of the box with no configuration required
- Fast: subsequent startups are instant (local YAML read, no network)

What makes it better than existing solutions (metamcp, tbxark/mcp-proxy, etc.):
- Unified YAML file that is simultaneously cache, config, and control plane — novel
- Smart refresh that never overwrites user settings
- Startup discovery-with-disconnect — all tools visible immediately, nothing running
- Tool-level filtering already implemented in proxy core
- No GUI required, no Docker required, no manual tool declaration required

---

## The Unified YAML File

**Location:** `~/.config/multi-mcp/servers.yaml`

One file. Cache, config, and tool control simultaneously. The only file the user ever touches.

### Full Schema

```yaml
servers:
  github:
    command: /home/tanner/mcp-servers/run-github.sh
    always_on: true
    tools:
      search_repositories:
        enabled: true
      create_gist:
        enabled: false
      delete_repository:
        enabled: false
      # ... remaining tools auto-populated on first run

  exa:
    type: sse
    url: https://mcp.exa.ai/mcp?tools=web_search_exa,get_code_context_exa,company_research_exa,crawling_exa,deep_researcher_start,deep_researcher_check
    always_on: false
    tools:
      # auto-populated on first run, all enabled: true by default

  obsidian:
    command: /home/tanner/mcp-servers/run-obsidian.sh
    always_on: true
    tools:
      # auto-populated on first run

  tavily:
    command: /home/tanner/mcp-servers/run-tavily.sh
    always_on: false
    tools:
      # auto-populated on first run

  sequential-thinking:
    command: npx -y @modelcontextprotocol/server-sequential-thinking
    always_on: false
    tools:
      # auto-populated on first run

  context7:
    command: npx -y @upstash/context7-mcp
    always_on: false
    tools:
      # auto-populated on first run
```

### Tool Control Rules

| Scenario | Behavior |
|----------|----------|
| No `tools` key for server | All tools pass through |
| `enabled: true` | Exposed to AI |
| `enabled: false` | Hidden from AI, user setting never overwritten by refresh |
| New tool discovered on refresh | Added as `enabled: true` |
| Tool gone from server on refresh | Marked `stale: true`, setting preserved |
| `stale: true` + `enabled: false` | Cleaned up on next refresh if still absent |

---

## Startup Behavior

### First Run (no YAML exists)
1. Connect to each configured server
2. Fetch full tool list from each
3. Write `servers.yaml` — all tools set `enabled: true`
4. Disconnect lazy servers (always_on: false)
5. Keep always_on servers connected
6. Serve tool list to AI clients — ready

### Subsequent Startups
1. Read `servers.yaml` — instant, zero network calls
2. Connect always_on servers
3. Lazy servers: serve tool metadata from cache, do not connect
4. Ready — fast as a config file read

### Manual Refresh
```bash
multi-mcp refresh              # re-discover all servers, smart merge
multi-mcp refresh github       # re-discover one server only
```

**Smart merge rules (refresh never touches user settings):**
- New tool found → add with `enabled: true`
- Existing tool → preserve `enabled` value, update description/schema only
- Tool gone from server → add `stale: true`, preserve `enabled` value
- `always_on` and server-level settings → never modified by refresh

---

## Lazy Loading

```
Startup:
  For each server:
    connect → fetch tool list → write to YAML → disconnect (if not always_on)

Runtime (lazy server):
  AI calls tool
    → proxy reconnects server
    → executes call
    → idle timeout starts
    → auto-disconnect after N minutes idle (configurable, default: 5 min)

Runtime (always_on server):
  Connected permanently, reconnects automatically on failure
```

Key design: tool metadata is served from YAML cache at startup so all tools are visible to the AI immediately. No server needs to be connected for its tools to appear. The backend only starts when a tool is actually called.

---

## CLI

```bash
# Start the proxy
multi-mcp start                          # stdio mode (default)
multi-mcp start --transport sse          # SSE mode on default port
multi-mcp start --transport sse --port 8085

# Tool discovery
multi-mcp refresh                        # re-discover all, smart merge
multi-mcp refresh <server>               # re-discover one server

# Visibility
multi-mcp status                         # connected servers, uptime, tool counts
multi-mcp list                           # all tools: server, name, enabled/disabled/stale
multi-mcp list --server github           # tools for one server only
multi-mcp list --disabled                # only filtered-out tools
```

---

## Config for Each AI Tool

Once multi-mcp is running, every tool points at it instead of individual servers.

**stdio mode** (simplest — one entry per tool):
```json
{
  "mcpServers": {
    "multi-mcp": {
      "type": "stdio",
      "command": "multi-mcp",
      "args": ["start"]
    }
  }
}
```

**SSE mode** (if running as a background service):
```json
{
  "mcpServers": {
    "multi-mcp": {
      "type": "sse",
      "url": "http://localhost:8085/sse"
    }
  }
}
```

This replaces all individual server entries in Claude Code, Codex, OpenCode, Antigravity, and Copilot configs.

---

## What's Already Built

| Feature | Status |
|---------|--------|
| Core proxy — request routing, namespacing | ✅ Done |
| Lazy loading via `pending_configs` | ✅ Done |
| Tool filtering — allow/deny per server | ✅ Done |
| Dynamic server add/remove via HTTP API | ✅ Done |
| SSE + stdio transport | ✅ Done |
| Audit logging | ✅ Done |
| API key auth | ✅ Done |
| Keyword trigger system | ✅ Done (may be superseded) |

## What Needs Building

| Feature | Priority |
|---------|----------|
| Startup discovery-with-disconnect | P0 |
| Unified YAML cache/config | P0 |
| Smart refresh with merge logic | P0 |
| `always_on` vs lazy per server | P0 |
| Idle timeout auto-disconnect | P0 |
| `multi-mcp` CLI entry point | P0 |
| `multi-mcp list` / `status` commands | P1 |
| Stale tool cleanup | P1 |
| Auto-reconnect on always_on failure | P1 |
| Update all AI tool configs to point at multi-mcp | P1 |

---

## Out of Scope (This Project)

- TUI — YAML is sufficient
- Semantic router / vault indexing — separate future project
- Embedding-based tool routing — separate future project
- Kubernetes / Docker deployment
- Multi-user / multi-tenant support
