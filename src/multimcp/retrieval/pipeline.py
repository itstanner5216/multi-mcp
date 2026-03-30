"""RetrievalPipeline — single entry point for tool filtering and ranking."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from mcp import types

from .base import ToolRetriever
from .logging import RetrievalLogger
from .models import (
    RankingEvent,
    RetrievalConfig,
    RetrievalContext,
    ScoredTool,
    WorkspaceEvidence,
)
from .session import SessionStateManager

# Optional imports — these are injected when wiring is complete
try:
    from .fusion import weighted_rrf as _weighted_rrf, compute_alpha as _compute_alpha  # noqa: F401
    _HAS_FUSION = True
except ImportError:
    _HAS_FUSION = False

try:
    from .routing_tool import build_routing_tool_schema
    _HAS_ROUTING_TOOL = True
except ImportError:
    _HAS_ROUTING_TOOL = False
    build_routing_tool_schema = None  # type: ignore[assignment]

try:
    from .rollout import get_session_group
except ImportError:
    def get_session_group(session_id: str, config: "RetrievalConfig") -> str:  # type: ignore[misc]
        return "control"

try:
    from .static_categories import STATIC_CATEGORIES, TIER6_NAMESPACE_PRIORITY
    _HAS_STATIC_CATEGORIES = True
except ImportError:
    _HAS_STATIC_CATEGORIES = False
    STATIC_CATEGORIES = {}  # type: ignore[assignment]
    TIER6_NAMESPACE_PRIORITY = []  # type: ignore[assignment]

try:
    from .telemetry.scanner import TelemetryScanner
    _HAS_TELEMETRY = True
except ImportError:
    _HAS_TELEMETRY = False
    TelemetryScanner = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping
    from .ranker import RelevanceRanker
    from .assembler import TieredAssembler


# ── Conversation term extraction ─────────────────────────────────────────────

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be",
    "to", "of", "and", "in", "for", "on", "with",
    "true", "false", "null", "none",
})

_ACTION_VERB_LEXICON: dict[str, list[str]] = {
    "list": ["get", "fetch", "show", "enumerate"],
    "create": ["add", "new", "make", "insert"],
    "search": ["find", "query", "lookup"],
    "delete": ["remove", "destroy", "drop"],
    "update": ["edit", "modify", "change", "patch"],
    "run": ["execute", "invoke", "start"],
    "get": ["fetch", "read", "retrieve"],
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _extract_conv_terms(raw: str) -> str:
    """Apply deterministic extraction pipeline to raw conversation context.

    Steps (in order):
    1. Lowercase
    2. Replace _ and - with spaces
    3. Tokenize with [a-z0-9]+
    4. Remove stopwords
    5. Deduplicate (first occurrence wins)
    6. Generate adjacent non-stopword bigrams
    7. Expand action verbs from lexicon
    8. Deduplicate final list
    9. Return space-joined result
    """
    text = raw.lower().replace("_", " ").replace("-", " ")
    tokens = _TOKEN_RE.findall(text)

    # Remove stopwords and deduplicate
    clean: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t not in _STOPWORDS and t not in seen:
            seen.add(t)
            clean.append(t)

    # Adjacent bigrams from clean tokens
    bigrams: list[str] = []
    for i in range(len(clean) - 1):
        bigram = clean[i] + " " + clean[i + 1]
        bigrams.append(bigram)

    combined = clean + bigrams

    # Action verb expansion
    expansions: list[str] = []
    for t in clean:
        if t in _ACTION_VERB_LEXICON:
            expansions.extend(_ACTION_VERB_LEXICON[t])

    combined.extend(expansions)

    # Final dedup preserving first occurrence
    final: list[str] = []
    final_seen: set[str] = set()
    for t in combined:
        if t not in final_seen:
            final_seen.add(t)
            final.append(t)

    return " ".join(final)


class RetrievalPipeline:
    """Orchestrates tool retrieval, ranking, and session state.

    When disabled: returns all tools (backward compatible).
    When enabled: returns session's active tool set (anchors + disclosed).
    """

    def __init__(
        self,
        retriever: ToolRetriever,
        session_manager: SessionStateManager,
        logger: RetrievalLogger,
        config: RetrievalConfig,
        tool_registry: dict[str, "ToolMapping"],
        ranker: Optional["RelevanceRanker"] = None,
        assembler: Optional["TieredAssembler"] = None,
        telemetry_scanner: Optional["TelemetryScanner"] = None,
    ) -> None:
        self.retriever = retriever
        self.session_manager = session_manager
        self.logger = logger
        self.config = config
        self.tool_registry = tool_registry  # Reference, not copy
        self.ranker = ranker
        self.assembler = assembler
        self._telemetry_scanner = telemetry_scanner
        self._session_turns: dict[str, int] = {}  # session_id -> current turn number
        # Telemetry / roots state
        self._session_roots: dict[str, list[str]] = {}
        self._session_evidence: dict[str, WorkspaceEvidence] = {}
        # Conversation context stores
        self._session_tool_history: dict[str, list[str]] = {}
        self._session_arg_keys: dict[str, list[str]] = {}
        self._session_router_describes: dict[str, list[str]] = {}

    # ── Session roots / telemetry ─────────────────────────────────────────────

    async def set_session_roots(self, session_id: str, root_uris: list[str]) -> None:
        """Store root URIs for a session and immediately run telemetry scanner.

        Called by mcp_proxy.py after roots/list response or roots/list_changed.
        Caches WorkspaceEvidence so get_tools_for_list() can use it at turn zero.
        """
        self._session_roots[session_id] = root_uris
        if self.config.enable_telemetry and self._telemetry_scanner is not None:
            evidence = self._telemetry_scanner.scan_roots(root_uris)
            self._session_evidence[session_id] = evidence

    # ── Session context accessors ─────────────────────────────────────────────

    def get_session_tool_history(self, session_id: str) -> list[str]:
        """Return tool names called in this session, in call order."""
        return list(self._session_tool_history.get(session_id, []))

    def get_session_argument_keys(self, session_id: str) -> list[str]:
        """Return argument key names from recent tool calls, in call order."""
        return list(self._session_arg_keys.get(session_id, []))

    def get_session_router_describes(self, session_id: str) -> list[str]:
        """Return tool names the model asked to describe via routing tool, in call order."""
        return list(self._session_router_describes.get(session_id, []))

    # ── Index availability helpers ────────────────────────────────────────────

    def _index_available(self) -> bool:
        """True if the retriever has a built index (BMXFRetriever with snapshot)."""
        return (
            self.retriever is not None
            and hasattr(self.retriever, "_env_index")
            and self.retriever._env_index is not None  # type: ignore[union-attr]
        )

    def _keyword_retriever_available(self) -> bool:
        """True if a fallback keyword retriever is available."""
        # Check if there's a keyword retriever attached (via _keyword_retriever attr)
        kr = getattr(self, "_keyword_retriever", None)
        return kr is not None

    def _has_frequency_prior(self) -> bool:
        """True if FileRetrievalLogger JSONL log exists with recent events."""
        log_path = getattr(self.logger, "_path", None)
        if log_path is None:
            return False
        p = Path(log_path)
        if not p.exists():
            return False
        return True

    # ── Tier 4: Static category defaults ─────────────────────────────────────

    def _classify_project_type(
        self, evidence: Optional[WorkspaceEvidence]
    ) -> tuple[Optional[str], bool]:
        """Return (project_type, is_confident) based on telemetry tokens.

        Classification precedence (first match wins):
        1. infrastructure — terraform/kubernetes/helm signals
        2. rust_cli       — Cargo.toml or lang:rust
        3. python_web     — pyproject.toml or lang:python
        4. node_web       — package.json or lang:javascript/typescript
        5. generic        — workspace_confidence >= 0.45
        6. Not confident  — fall through to Tier 5
        """
        if evidence is None:
            return None, False

        tokens = evidence.merged_tokens
        token_keys = set(tokens.keys())

        infra_signals = {"infra:terraform", "infra:kubernetes", "manifest:Chart.yaml"}
        if token_keys & infra_signals:
            return "infrastructure", True

        if "manifest:Cargo.toml" in token_keys or "lang:rust" in token_keys:
            return "rust_cli", True

        if "manifest:pyproject.toml" in token_keys or "lang:python" in token_keys:
            return "python_web", True

        if (
            "manifest:package.json" in token_keys
            or "lang:javascript" in token_keys
            or "lang:typescript" in token_keys
        ):
            return "node_web", True

        if evidence.workspace_confidence >= 0.45:
            return "generic", True

        return None, False

    def _static_category_defaults(
        self, project_type: str, dynamic_k: int
    ) -> list[ScoredTool]:
        """Return ScoredTool list for the given project type using STATIC_CATEGORIES.

        always-tier tools score 1.0, likely-tier tools score 0.8.
        Result is capped at dynamic_k.
        """
        if not _HAS_STATIC_CATEGORIES or project_type not in STATIC_CATEGORIES:
            return []

        category = STATIC_CATEGORIES[project_type]
        always_ns = category.get("always", [])
        likely_ns = category.get("likely", [])

        result: list[ScoredTool] = []
        selected_keys: set[str] = set()

        # Select from always-tier namespaces
        for ns in always_ns:
            for key, mapping in self.tool_registry.items():
                if key not in selected_keys and mapping.server_name == ns:
                    result.append(ScoredTool(tool_key=key, tool_mapping=mapping, score=1.0))
                    selected_keys.add(key)
                    break  # one tool per namespace for static category

        # Select from likely-tier namespaces (if room)
        for ns in likely_ns:
            if len(result) >= dynamic_k:
                break
            for key, mapping in self.tool_registry.items():
                if key not in selected_keys and mapping.server_name == ns:
                    result.append(ScoredTool(tool_key=key, tool_mapping=mapping, score=0.8))
                    selected_keys.add(key)
                    break

        return result[:dynamic_k]

    # ── Tier 5: Time-decayed frequency prior ─────────────────────────────────

    def _frequency_prior_tools(self, dynamic_k: int) -> list[ScoredTool]:
        """Return time-decayed frequency prior from FileRetrievalLogger JSONL.

        Time window: last 7 days.
        Excludes shadow group events.
        Counts direct_tool_calls + router_proxies fields.
        Score = sum of exp(-0.1 * days_ago) per occurrence.
        """
        import math

        log_path = getattr(self.logger, "_path", None)
        if log_path is None:
            return []

        p = Path(log_path)
        if not p.exists():
            return []

        cutoff_epoch = time.time() - 7 * 24 * 3600
        scores: dict[str, float] = {}

        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Skip non-ranking events and shadow group
                    if event.get("type") == "alert":
                        continue
                    if event.get("group") == "shadow":
                        continue

                    # Check timestamp
                    ts = event.get("timestamp") or event.get("scorer_latency_ms")
                    # RankingEvent doesn't have a timestamp field — use session_id presence
                    # as a heuristic that it's a valid ranking event.
                    # For frequency prior we need the log's mtime as proxy if no ts.
                    # Use file mtime / line-number-based estimation is impractical;
                    # check if event has a recognizable timestamp field.
                    event_time = event.get("event_time") or event.get("ts")
                    if event_time is None:
                        # Try to use scorer_latency_ms as existence check only
                        # (no timestamp in RankingEvent schema — use file mtime as fallback)
                        # Use file mtime; if file is newer than 7 days it may contain old entries
                        # Conservative: count ALL non-shadow entries (no time filter possible)
                        days_ago = 0.0
                    else:
                        event_ts = float(event_time)
                        if event_ts < cutoff_epoch:
                            continue
                        days_ago = (time.time() - event_ts) / 86400.0

                    decay = math.exp(-0.1 * days_ago)

                    for tool_name in event.get("direct_tool_calls", []):
                        scores[tool_name] = scores.get(tool_name, 0.0) + decay

                    for tool_name in event.get("router_proxies", []):
                        scores[tool_name] = scores.get(tool_name, 0.0) + decay

        except OSError:
            return []

        if not scores:
            return []

        # Sort by descending score
        sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        result: list[ScoredTool] = []
        for key, score in sorted_tools[:dynamic_k]:
            if key in self.tool_registry:
                result.append(
                    ScoredTool(
                        tool_key=key,
                        tool_mapping=self.tool_registry[key],
                        score=score,
                    )
                )

        return result[:dynamic_k]

    # ── Tier 6: Universal 12-tool fallback ───────────────────────────────────

    def _universal_fallback(self) -> list[ScoredTool]:
        """Return universal 12-tool set using TIER6_NAMESPACE_PRIORITY order.

        Algorithm:
        1. For each namespace in priority order, pick lexicographically smallest key
        2. If fewer than 12 selected, fill with lex-smallest remaining keys
        3. Expose at most 12 direct tools
        """
        selected: list[ScoredTool] = []
        selected_keys: set[str] = set()

        if _HAS_STATIC_CATEGORIES:
            priority = TIER6_NAMESPACE_PRIORITY
        else:
            priority = []

        # Build namespace → sorted keys map
        ns_keys: dict[str, list[str]] = {}
        for key, mapping in self.tool_registry.items():
            ns = mapping.server_name
            if ns not in ns_keys:
                ns_keys[ns] = []
            ns_keys[ns].append(key)
        for ns in ns_keys:
            ns_keys[ns].sort()

        # Step 1: namespace priority pass
        for ns in priority:
            if len(selected) >= 12:
                break
            if ns in ns_keys:
                for key in ns_keys[ns]:
                    if key not in selected_keys:
                        selected.append(
                            ScoredTool(
                                tool_key=key,
                                tool_mapping=self.tool_registry[key],
                                score=1.0,
                            )
                        )
                        selected_keys.add(key)
                        break

        # Step 2: fill remaining with lex-smallest unselected keys
        if len(selected) < 12:
            remaining = sorted(
                k for k in self.tool_registry if k not in selected_keys
            )
            for key in remaining:
                if len(selected) >= 12:
                    break
                selected.append(
                    ScoredTool(
                        tool_key=key,
                        tool_mapping=self.tool_registry[key],
                        score=0.5,
                    )
                )
                selected_keys.add(key)

        return selected[:12]

    # ── Main pipeline entry point ─────────────────────────────────────────────

    async def get_tools_for_list(
        self, session_id: str, conversation_context: str = ""
    ) -> list[types.Tool]:
        """Called by _list_tools(). Returns tool list based on pipeline state.

        When disabled: returns ALL tools including cached/disconnected (client=None).
        When enabled: runs tiered fallback scoring pipeline and returns bounded set.
        """
        # Master kill switch — enabled=False always returns all tools
        if not self.config.enabled:
            return [m.tool for m in self.tool_registry.values()]

        t0 = time.monotonic()

        # Determine session group for canary routing
        group = get_session_group(session_id, self.config)

        # Shadow mode: score but return all tools (backward compatible)
        # Control sessions in canary mode also get all tools
        is_filtered = (
            self.config.rollout_stage == "ga"
            or (self.config.rollout_stage == "canary" and group == "canary")
        )

        # Ensure session exists
        self.session_manager.get_or_create_session(session_id)
        active_keys = self.session_manager.get_active_tools(session_id)

        all_registry_keys = list(self.tool_registry.keys())
        candidates = list(self.tool_registry.values())

        # Dynamic K: base 15, +3 if polyglot (>1 distinct lang: token), cap 20
        dynamic_k = 15
        evidence = self._session_evidence.get(session_id)
        if evidence:
            lang_tokens = [k for k in evidence.merged_tokens if k.startswith("lang:")]
            if len(lang_tokens) > 1:
                dynamic_k = 18
        dynamic_k = min(20, dynamic_k)

        # Reserve one slot for routing tool if enabled
        if self.config.enable_routing_tool and _HAS_ROUTING_TOOL:
            direct_k = max(1, dynamic_k - 1)
        else:
            direct_k = dynamic_k

        # Session context
        turn = self._session_turns.get(session_id, 0)
        workspace_evidence: Optional[WorkspaceEvidence] = evidence

        # ── Build query strings ──────────────────────────────────────────────

        # Env query from workspace evidence tokens
        env_query = ""
        if workspace_evidence and workspace_evidence.merged_tokens:
            env_query = " ".join(
                f"{k}:{v}" if ":" not in k else k
                for k in workspace_evidence.merged_tokens
            )
            # Simpler: join keys as query terms
            env_query = " ".join(workspace_evidence.merged_tokens.keys())

        # Conv query from extracted terms
        conv_query = ""
        if conversation_context:
            conv_query = _extract_conv_terms(conversation_context)

        # Confidence signals for alpha computation
        ws_confidence = workspace_evidence.workspace_confidence if workspace_evidence else 0.0
        conv_confidence = min(1.0, len(conv_query.split()) / 10.0) if conv_query else 0.0
        roots_changed = False  # tracked by set_session_roots caller
        explicit_tool_mention = any(
            k in conv_query for k in all_registry_keys
        ) if conv_query else False

        # ── 6-tier fallback ladder ────────────────────────────────────────────

        fallback_tier = 1
        scored_tools: Optional[list[ScoredTool]] = None

        # Build RetrievalContext helpers
        def _env_ctx() -> RetrievalContext:
            return RetrievalContext(
                session_id=session_id,
                query=env_query,
                query_mode="env",
            )

        def _conv_ctx() -> RetrievalContext:
            return RetrievalContext(
                session_id=session_id,
                query=conv_query,
                query_mode="nl",
            )

        # Tier 1: BMXF env + conv blend (normal operation, turn > 0)
        if (
            scored_tools is None
            and self._index_available()
            and env_query
            and conv_query
            and turn > 0
            and _HAS_FUSION
        ):
            try:
                env_ranked = await self.retriever.retrieve(_env_ctx(), candidates)
                conv_ranked = await self.retriever.retrieve(_conv_ctx(), candidates)
                alpha = _compute_alpha(
                    turn=turn,
                    workspace_confidence=ws_confidence,
                    conv_confidence=conv_confidence,
                    roots_changed=roots_changed,
                    explicit_tool_mention=explicit_tool_mention,
                )
                scored_tools = _weighted_rrf(env_ranked, conv_ranked, alpha)
                fallback_tier = 1
            except Exception:
                scored_tools = None

        # Tier 2: BMXF env-only (conv query weak/empty or tier 1 failed)
        if scored_tools is None and self._index_available() and env_query:
            try:
                scored_tools = await self.retriever.retrieve(_env_ctx(), candidates)
                fallback_tier = 2
            except Exception:
                scored_tools = None

        # Tier 3: KeywordRetriever env-only (BMXF unavailable)
        if scored_tools is None and self._keyword_retriever_available() and env_query:
            try:
                kr = getattr(self, "_keyword_retriever")
                scored_tools = await kr.retrieve(_env_ctx(), candidates)
                fallback_tier = 3
            except Exception:
                scored_tools = None

        # Tier 4: Static category defaults (project_type_guess confident)
        if scored_tools is None:
            project_type, project_type_confident = self._classify_project_type(
                workspace_evidence
            )
            if project_type_confident and project_type is not None and _HAS_STATIC_CATEGORIES:
                scored_tools = self._static_category_defaults(project_type, dynamic_k)
                if scored_tools:
                    fallback_tier = 4
                else:
                    scored_tools = None

        # Tier 5: Time-decayed frequency prior (7-day)
        if scored_tools is None and self._has_frequency_prior():
            freq_tools = self._frequency_prior_tools(dynamic_k)
            if freq_tools:
                scored_tools = freq_tools
                fallback_tier = 5

        # Tier 6: Universal 12-tool set + routing tool
        if scored_tools is None:
            scored_tools = self._universal_fallback()
            fallback_tier = 6

        # ── Select active set from scored tools ───────────────────────────────

        # Sort by descending score and take top direct_k
        scored_tools.sort(key=lambda s: s.score, reverse=True)
        active_scored = scored_tools[:direct_k]

        active_key_set = {s.tool_key for s in active_scored}
        demoted_ids = [k for k in all_registry_keys if k not in active_key_set]

        # Enforce invariant: never expose more than 20 direct tools
        if len(active_scored) > 20:
            active_scored = active_scored[:20]

        # Update session manager with new active set
        if active_keys != active_key_set:
            self.session_manager.get_or_create_session(session_id)
            if hasattr(self.session_manager, "set_active_tools"):
                self.session_manager.set_active_tools(session_id, active_key_set)

        latency_ms = (time.monotonic() - t0) * 1000.0

        # Get catalog version if available
        catalog_version = ""
        if hasattr(self.retriever, "get_snapshot_version"):
            catalog_version = self.retriever.get_snapshot_version()

        # Emit RankingEvent (OBS-02)
        event = RankingEvent(
            session_id=session_id,
            turn_number=turn,
            catalog_version=catalog_version,
            workspace_hash=workspace_evidence.workspace_hash if workspace_evidence else None,
            workspace_confidence=ws_confidence,
            conv_confidence=conv_confidence,
            alpha=ws_confidence,  # approximate; exact alpha only computed in tier 1
            active_k=len(active_scored),
            fallback_tier=fallback_tier,
            active_tool_ids=[s.tool_key for s in active_scored],
            router_enum_size=len(demoted_ids),
            scorer_latency_ms=latency_ms,
            group=group,
        )
        await self.logger.log_ranking_event(event)

        if is_filtered:
            # CANARY/GA: return bounded active set + routing tool
            routing_schema = None
            if (
                self.config.enable_routing_tool
                and demoted_ids
                and _HAS_ROUTING_TOOL
                and build_routing_tool_schema is not None
            ):
                routing_schema = build_routing_tool_schema(demoted_ids)

            if self.ranker is not None and self.assembler is not None:
                ranked = self.ranker.rank(active_scored)
                result = self.assembler.assemble(
                    ranked, self.config, routing_tool_schema=routing_schema
                )
            else:
                result = [s.tool_mapping.tool for s in active_scored]
                if routing_schema is not None:
                    result.append(routing_schema)
        else:
            # SHADOW/CONTROL: return all tools (passthrough)
            result = [m.tool for m in self.tool_registry.values()]

        return result

    def rebuild_catalog(self, registry: "dict[str, ToolMapping]") -> None:
        """Rebuild the retriever's index when the tool registry changes.

        Called by MCPProxyServer.register_client() and unregister_client()
        after any registry mutation (WIRE-02). No-op if retriever does not
        implement rebuild_index (e.g. PassthroughRetriever).
        """
        rebuild = getattr(self.retriever, "rebuild_index", None)
        if callable(rebuild):
            rebuild(registry)

    async def on_tool_called(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
    ) -> bool:
        """Called by _call_tool(). Tracks turns and triggers promote/demote evaluation.

        Returns True if active set changed (caller should send list_changed notification).
        """
        if not self.config.enabled:
            return False

        # Increment turn counter for this session
        self._session_turns[session_id] = self._session_turns.get(session_id, 0) + 1

        # Track session tool history for conversation context
        hist = self._session_tool_history.setdefault(session_id, [])
        hist.append(tool_name)

        # Track argument keys
        arg_keys = self._session_arg_keys.setdefault(session_id, [])
        arg_keys.extend(arguments.keys())

        # Record tool usage for demote safety (used_this_turn)
        # Demote evaluation is delegated to pipeline on the NEXT turn boundary
        # For now: disclose any new tools based on what was called (promote via usage signal)
        if hasattr(self.session_manager, 'promote') and tool_name in self.tool_registry:
            newly_added = self.session_manager.promote(session_id, [tool_name])
            return len(newly_added) > 0

        return False
