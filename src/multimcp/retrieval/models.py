"""Core data models for the retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping


@dataclass
class RetrievalContext:
    """Carries the signal for retrieval operations."""
    session_id: str
    query: str = ""
    tool_call_history: list[str] = field(default_factory=list)
    server_hint: Optional[str] = None


@dataclass
class ScoredTool:
    """A tool with its retrieval score and tier assignment."""
    tool_key: str
    tool_mapping: "ToolMapping"
    score: float = 1.0
    tier: Literal["full", "summary"] = "full"


@dataclass
class RetrievalConfig:
    """Pipeline configuration with sensible defaults.

    Phase 2 fields (shadow_mode, scorer, max_k, enable_routing_tool,
    enable_telemetry, telemetry_poll_interval) all default to safe values
    so existing configs (enabled=False) remain fully backward compatible.
    """
    # Existing fields — unchanged
    enabled: bool = False
    top_k: int = 10
    full_description_count: int = 3
    anchor_tools: list[str] = field(default_factory=list)
    # Phase 2 additions
    shadow_mode: bool = False
    scorer: str = "bmxf"
    max_k: int = 20
    enable_routing_tool: bool = True
    enable_telemetry: bool = True
    telemetry_poll_interval: int = 30
    # Phase 4: Rollout hardening
    canary_percentage: float = 0.0        # 0.0-100.0; % of sessions routed to BMXF filtering
    rollout_stage: str = "shadow"         # "shadow" | "canary" | "ga"


# === Phase 2: Tool catalog types ===

@dataclass
class ToolDoc:
    """Canonical retrieval document for a single tool.

    Maps to ToolMapping: tool_key from _make_key(), fields from types.Tool.
    retrieval_aliases is space-joined curated lexical synonyms populated by
    BMXFRetriever._generate_aliases() — empty string when not yet assigned.
    """
    tool_key: str                   # server_name__tool_name (double underscore)
    tool_name: str                  # tool.name (without server prefix)
    namespace: str                  # server_name
    description: str                # tool.description or ""
    parameter_names: str            # space-joined keys from tool.inputSchema.properties
    retrieval_aliases: str          # curated lexical aliases, space-joined


@dataclass
class ToolCatalogSnapshot:
    """Immutable versioned index of all tools.

    schema_hash is SHA-256 of sorted canonical tool docs (sorted by tool_key).
    Stable for identical registry states; changes on any tool schema update.
    """
    version: str
    schema_hash: str                # SHA-256 hex digest
    built_at: float                 # time.time() at build
    docs: list[ToolDoc] = field(default_factory=list)


# === Phase 2: Telemetry types ===

@dataclass
class RootEvidence:
    """Evidence derived from scanning a single MCP root."""
    root_uri: str
    root_name: Optional[str] = None
    tokens: dict[str, float] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    fingerprint_hash: str = ""
    partial_scan: bool = False


@dataclass
class WorkspaceEvidence:
    """Composition of all root evidence for this session."""
    roots: list[RootEvidence] = field(default_factory=list)
    workspace_confidence: float = 0.0
    merged_tokens: dict[str, float] = field(default_factory=dict)
    workspace_hash: str = ""


# === Phase 2: Session routing state ===

@dataclass
class SessionRoutingState:
    """Per-session mutable state for ranking and routing.

    Replaces the monotonic guarantee in SessionStateManager for Phase 2.
    Never shared across sessions — always constructed per session_id.
    """
    session_id: str
    catalog_version: str = ""
    turn_number: int = 0
    env_hash: Optional[str] = None
    env_confidence: float = 0.0
    conv_confidence: float = 0.0
    alpha: float = 0.85
    active_k: int = 15
    fallback_tier: int = 1
    active_tool_ids: list[str] = field(default_factory=list)
    router_enum_tool_ids: list[str] = field(default_factory=list)
    recent_router_describes: list[str] = field(default_factory=list)
    recent_router_proxies: list[str] = field(default_factory=list)
    last_rank_scores: dict[str, float] = field(default_factory=dict)
    consecutive_low_rank: dict[str, int] = field(default_factory=dict)


# === Phase 2: Observability ===

@dataclass
class RankingEvent:
    """Structured log entry for every ranking decision.

    Emitted per-turn to RetrievalLogger. Enables offline replay evaluation
    and online metrics (describe rate, tier distribution, scorer latency).
    """
    session_id: str
    turn_number: int
    catalog_version: str
    workspace_hash: Optional[str] = None
    workspace_confidence: float = 0.0
    conv_confidence: float = 0.0
    alpha: float = 0.0
    active_k: int = 0
    fallback_tier: int = 0
    active_tool_ids: list[str] = field(default_factory=list)
    router_enum_size: int = 0
    direct_tool_calls: list[str] = field(default_factory=list)
    router_describes: list[str] = field(default_factory=list)
    router_proxies: list[str] = field(default_factory=list)
    scorer_latency_ms: float = 0.0
    group: str = "control"                # "canary" | "control" — set by pipeline
