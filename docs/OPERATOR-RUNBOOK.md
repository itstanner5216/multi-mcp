# BMXF Routing — Operator Runbook

## Overview

BMXF (field-weighted BMX) routing replaces the `PassthroughRetriever` (all tools visible) with a context-aware retrieval pipeline that exposes a bounded active set (K=15-20 tools) with remaining tools accessible via a routing tool.

## Configuration

### RetrievalConfig Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `False` | **Master kill switch.** When False, all tools returned regardless of other settings. |
| `rollout_stage` | str | `"shadow"` | `"shadow"` \| `"canary"` \| `"ga"` — controls which sessions get BMXF filtering. |
| `canary_percentage` | float | `0.0` | 0.0-100.0 — percentage of sessions routed to BMXF in canary stage. |
| `shadow_mode` | bool | `False` | When True, BMXFRetriever scores but returns all candidates (scoring without filtering). |
| `max_k` | int | `20` | Maximum tools in active set. Dynamic K: base 15, +3 if polyglot, cap 20. |
| `scorer` | str | `"bmxf"` | Scorer selection: `"bmxf"` \| `"keyword"` \| `"passthrough"`. |
| `enable_routing_tool` | bool | `True` | When True, demoted tools are accessible via the `request_tool` routing tool. |

### Rollout Stages

1. **Shadow** (`rollout_stage="shadow"`): BMXF scoring runs, RankingEvents logged, but all sessions see all tools. This is the observational phase.

2. **Canary** (`rollout_stage="canary"`): Sessions are hash-assigned to canary or control groups based on `canary_percentage`. Canary sessions get BMXF-filtered results; control sessions get all tools.

3. **GA** (`rollout_stage="ga"`): All sessions get BMXF-filtered results.

## Rollout Procedure

### Step 1: Verify Shadow Metrics

```bash
# Run replay evaluator against shadow logs
python -m src.multimcp.retrieval.replay /path/to/ranking_events.jsonl
```

**Required:** All cutover gates must pass:
- p95 scorer latency < 50ms
- Tier 5-6 rate < 5%

### Step 2: Enable Canary at 10%

```python
config = RetrievalConfig(
    enabled=True,
    rollout_stage="canary",
    canary_percentage=10.0,
)
```

**Monitor for 24h.** Check:
- Describe rate (canary group) — should be < 10%
- p95 latency (canary group) — should be < 50ms
- No Tier 5-6 events in canary group

### Step 3: Ramp to 50%

```python
config.canary_percentage = 50.0
```

**Monitor for 24h.** Same checks as Step 2.

### Step 4: Promote to GA

```python
config = RetrievalConfig(
    enabled=True,
    rollout_stage="ga",
)
```

## Alert Response

### HIGH_DESCRIBE_RATE (> 10%)

**Meaning:** More than 10% of turns involve the routing tool's describe action, indicating the active set is missing frequently-needed tools.

**Action:**
1. Check which tools are being described most (from RankingEvent.router_describes)
2. Consider adding them to `anchor_tools` in config
3. If widespread, the environment signals may be weak — check workspace_confidence
4. If sustained > 30min, consider rolling back canary_percentage

### HIGH_TIER56_RATE (> 5%)

**Meaning:** More than 5% of sessions are falling to degraded fallback tiers (static defaults or universal set).

**Action:**
1. Check if BMXFRetriever index is being rebuilt correctly (WIRE-02)
2. Verify tool registry is populated (check register_client logs)
3. If BMXF index is corrupt, set `scorer="keyword"` to fall back to TF-IDF

### HIGH_P95_LATENCY (> 75ms)

**Meaning:** Scoring is taking too long, likely due to large tool registry or slow index rebuild.

**Action:**
1. Check tool count — if > 300 tools, consider increasing telemetry_poll_interval
2. Verify no hot loop in adaptive polling (monitor.py backpressure should freeze polling to 15s)
3. If sustained, reduce max_k to lower the scoring window

## Emergency Rollback

### Immediate (< 1 minute)

```python
# Option 1: Kill switch
config.enabled = False

# Option 2: Back to shadow
config.rollout_stage = "shadow"
```

### Targeted (preserve canary data)

```python
# Reduce canary exposure
config.canary_percentage = 0.0
# All sessions become control, but canary stage preserved
```

### Full Revert

```python
config = RetrievalConfig(
    enabled=False,
    shadow_mode=True,  # Return to pre-Phase 4 state
)
```

## Monitoring

### Log Files

RankingEvent JSONL logs are written by `FileRetrievalLogger` to the configured path. Each line contains:

```json
{
  "session_id": "abc-123",
  "turn_number": 3,
  "active_k": 15,
  "fallback_tier": 1,
  "scorer_latency_ms": 12.5,
  "router_describes": [],
  "group": "canary"
}
```

### Key Metrics

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Describe rate | < 5% | 5-10% | > 10% |
| Tier 5-6 rate | < 1% | 1-5% | > 5% |
| p95 latency | < 30ms | 30-50ms | > 75ms |
| Active K avg | 14-16 | 12-18 | < 10 or > 20 |

### Replay Evaluation

Run offline evaluation against collected logs:

```bash
python -m src.multimcp.retrieval.replay /path/to/ranking_events.jsonl
```

This prints a gate report showing pass/fail status for each cutover criterion.
