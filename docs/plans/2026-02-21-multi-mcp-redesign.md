# Multi-MCP Redesign Design Doc
**Date:** 2026-02-21
**Status:** In Progress — pending lazy loading research review

---

## Goal

Make multi-mcp a production-ready, system-wide MCP proxy that:
- Lazily loads backend servers (connect only when needed)
- Exposes a single endpoint to all AI tools (Claude Code, Codex, OpenCode, Antigravity, Copilot)
- Lets the user control exactly which tools are visible with zero friction
- Works out of the box with no configuration required

---

## Approach

Extend the existing multi-mcp codebase (Python). The proxy core, lazy loading primitives, tool filtering, and HTTP API are already solid. The remaining work is the unified YAML file, smart refresh logic, startup discovery-with-disconnect, and a handful of CLI commands.

---

## The Unified YAML File

**Location:** `~/.config/multi-mcp/servers.yaml`

This single file serves as cache, config, and tool control simultaneously. It is the only file the user ever needs to touch.

### Schema

```yaml
servers:
  github:
    command: /home/tanner/mcp-servers/run-github.sh
    always_on: true                  # stays connected at all times
    tools:
      search_repositories:
        enabled: true
      create_gist:
        enabled: false               # user disabled this
      delete_repository:
        enabled: false
      # ... rest of 26 tools

  exa:
    type: sse
    url: https://mcp.exa.ai/mcp?tools=...
    always_on: false                 # lazy: connect on first tool call
    tools:
      web_search_exa:
        enabled: true
      linkedin_search_exa:
        enabled: false
      # ... rest

  obsidian:
    command: /home/tanner/mcp-servers/run-obsidian.sh
    always_on: true
    tools:
      read_note:
        enabled: true
      # ...

  tavily:
    command: /home/tanner/mcp-servers/run-tavily.sh
    always_on: false
    tools:
      # all enabled: true by default

  sequential-thinking:
    command: npx -y @modelcontextprotocol/server-sequential-thinking
    always_on: false
    tools:
      sequentialthinking:
        enabled: true

  context7:
    command: npx -y @upstash/context7-mcp
    always_on: false
    tools:
      resolve-library-id:
        enabled: true
      get-library-docs:
        enabled: true
```

### Tool Control Rules

| Scenario | Behavior |
|----------|----------|
| No `tools` key configured | All tools pass through (default) |
| Tool present, `enabled: true` | Exposed to AI |
| Tool present, `enabled: false` | Hidden from AI, backend still runs if connected |
| Tool not in YAML but discovered on refresh | Added with `enabled: true` |
| Tool in YAML but no longer on server | Marked `stale: true`, user setting preserved |

---

## Startup Behavior

### First Run (empty or missing cache)
1. Connect to each server briefly
2. Fetch full tool list
3. Write `servers.yaml` with all tools set to `enabled: true`
4. Disconnect lazy servers, keep always-on servers connected
5. Serve tool list to AI clients immediately

### Subsequent Startups
1. Read `servers.yaml` — instant, no network calls
2. Connect always-on servers
3. Lazy servers: advertise tools from cache, do not connect
4. Ready

### Manual Refresh
```bash
multi-mcp refresh           # re-discover all servers, smart merge
multi-mcp refresh github    # re-discover one server only
```

**Smart merge rules:**
- New tool discovered → add with `enabled: true`
- Existing tool → preserve `enabled` status, update metadata only
- Tool gone from server → set `stale: true`, preserve `enabled` status
- Never overwrites user-set values

---

## Lazy Loading Behavior

```
Startup:
  → connect all servers briefly (tool discovery)
  → cache to servers.yaml
  → disconnect lazy servers
  → keep always_on servers connected

Runtime (lazy server):
  AI calls tool → proxy reconnects server → executes → ...
  [idle timeout TBD — see lazy loading research review]
  → optionally disconnect after idle
```

The key design insight: tool metadata is served from the YAML cache at startup, so all tools are visible to the AI immediately without any server being connected. The backend only starts when a tool is actually invoked.

---

## CLI Commands

```bash
multi-mcp start             # start the proxy (stdio or SSE mode)
multi-mcp refresh [server]  # re-discover tools, smart merge into YAML
multi-mcp status            # show connected servers, tool counts
multi-mcp list              # list all tools across all servers (exposed/filtered/stale)
```

---

## What's Already Built

| Feature | Status |
|---------|--------|
| Core proxy (request routing, namespacing) | ✅ Done |
| Lazy loading via `pending_configs` | ✅ Done |
| Tool filtering (`allow`/`deny` per server) | ✅ Done (added today) |
| Dynamic add/remove via HTTP API | ✅ Done |
| SSE + stdio transport | ✅ Done |
| Startup discovery-with-disconnect | ❌ Needed |
| Unified YAML cache/config | ❌ Needed |
| Smart refresh (preserve user settings) | ❌ Needed |
| Idle timeout auto-disconnect | ⏳ Pending lazy loading research |
| CLI commands | ❌ Needed |

---

## Open Questions

1. **Lazy loading research** — User has research to review before finalizing idle timeout behavior and whether additional lazy loading patterns are worth implementing. See next section.
2. **Idle timeout** — Should lazy servers auto-disconnect after N minutes of inactivity, or stay connected once woken?
3. **System-wide config propagation** — After multi-mcp is set up, all tool configs (Claude Code, Codex, OpenCode, Antigravity, Copilot) need to be updated to point at the single multi-mcp endpoint.

---

## Out of Scope

- TUI — YAML is simple enough to edit directly
- Keyword-triggered wakeup — startup discovery-with-disconnect solves the visibility problem more cleanly
- Web UI
- Kubernetes/Docker deployment changes
