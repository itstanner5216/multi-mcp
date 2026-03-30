"""BMXF retriever — field-weighted BMX tool retrieval.

BMXFRetriever wraps BMXIndex.build_field_index / search_fields to provide
a ToolRetriever implementation that scores tools across 5 fields with
weighted sum fusion (BMXF). Runs in shadow mode by default: scoring proceeds
but retrieve() returns all candidates, so existing behaviour is unchanged
until shadow_mode=False.

Alias generation populates retrieval_aliases on each ToolDoc via curated
namespace and action synonym maps. This is scorer-side logic — catalog.py
intentionally leaves retrieval_aliases empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from .base import ToolRetriever
from .bmx_index import BMXIndex
from .catalog import build_snapshot
from .models import RetrievalConfig, RetrievalContext, ScoredTool, ToolCatalogSnapshot

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping

# ── Alias maps ──────────────────────────────────────────────────────────────
# NAMESPACE_ALIASES: server-name fragments → lexical synonyms.
# These bridge common abbreviated server names to natural-language terms so
# a user query like "file" also surfaces tools from a server named "fs".
NAMESPACE_ALIASES: dict[str, list[str]] = {
    "github": ["repository", "pull_request", "issue", "git", "code_review", "branch", "commit"],
    "brave-search": ["web_search", "internet", "lookup", "find", "query"],
    "context7": ["documentation", "library", "docs", "api_reference", "examples"],
    "docker": ["container", "image", "compose", "deploy", "service"],
    "filesystem": ["file", "directory", "read", "write", "path", "folder"],
    "shell": ["terminal", "command", "bash", "exec", "run", "process"],
    "slack": ["message", "channel", "chat", "notification"],
    "npm": ["package", "install", "node", "dependency"],
    "pip": ["package", "install", "python", "dependency"],
    "cargo": ["crate", "build", "rust", "compile"],
    "kubectl": ["kubernetes", "pod", "deployment", "service", "cluster"],
    "terraform": ["infrastructure", "cloud", "provision", "iac"],
}

# ACTION_ALIASES: action verbs found in tool names → synonyms.
# Bridges terminology mismatches (e.g. "create" matches "make", "add", "new").
ACTION_ALIASES: dict[str, list[str]] = {
    "create": ["make", "add", "new", "write", "generate", "insert"],
    "read": ["get", "fetch", "load", "retrieve", "open", "view", "show"],
    "update": ["edit", "modify", "change", "patch", "set", "write"],
    "delete": ["remove", "drop", "destroy", "erase", "clear"],
    "list": ["show", "get", "fetch", "enumerate", "find", "search"],
    "search": ["find", "query", "lookup", "filter", "grep"],
    "execute": ["run", "call", "invoke", "apply", "eval"],
    "send": ["post", "push", "emit", "publish", "submit"],
    "get": ["fetch", "read", "load", "retrieve", "show", "list"],
    "set": ["update", "write", "configure", "assign"],
    "check": ["validate", "verify", "test", "inspect"],
    "parse": ["extract", "decode", "transform", "convert"],
    "merge": ["combine", "join", "integrate"],
    "clone": ["copy", "duplicate"],
    "diff": ["compare", "contrast", "changes"],
    "log": ["history", "events", "audit", "record"],
    "status": ["state", "info", "health", "check"],
    "install": ["add", "setup", "configure"],
    "build": ["compile", "make", "generate"],
    "deploy": ["release", "publish", "ship"],
    "start": ["run", "launch", "begin"],
    "stop": ["kill", "terminate", "halt"],
    "open": ["read", "load", "view"],
    "close": ["finish", "end", "complete"],
}


class BMXFRetriever(ToolRetriever):
    """Field-weighted BMX retriever for MCP tool namespaces.

    rebuild_index(registry) must be called before retrieve() is useful.
    In shadow mode (default), retrieve() scores tools but returns all
    candidates — identical to PassthroughRetriever. Set shadow_mode=False
    to enable bounded retrieval.
    """

    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self._config = config or RetrievalConfig(shadow_mode=True)
        # Dual indexes: env uses alpha_override=0.5, nl uses auto-tune (alpha_override=None)
        self._env_index: BMXIndex | None = None
        self._nl_index: BMXIndex | None = None
        # Legacy single index — kept for backward compat; same as _env_index after rebuild
        self._index: BMXIndex | None = None
        self._snapshot: ToolCatalogSnapshot | None = None
        # tool_key → ToolDoc mapping, populated by rebuild_index
        self._doc_by_key: dict[str, object] = {}

    # ── Alias generation ────────────────────────────────────────────────────

    def _generate_aliases(self, tool_name: str, namespace: str) -> str:
        """Produce space-joined alias tokens for a tool.

        Matches namespace against NAMESPACE_ALIASES and each word of tool_name
        against ACTION_ALIASES. Returns deduplicated space-joined string.
        """
        aliases: list[str] = []

        # Namespace aliases — exact server name key lookup (not substring matching)
        ns_lower = namespace.lower()
        if ns_lower in NAMESPACE_ALIASES:
            aliases.extend(NAMESPACE_ALIASES[ns_lower])

        # Action aliases from tool name words
        name_words = tool_name.replace("_", " ").replace("-", " ").lower().split()
        for word in name_words:
            if word in ACTION_ALIASES:
                aliases.extend(ACTION_ALIASES[word])

        # Deduplicate preserving first-occurrence order
        seen: set[str] = set()
        deduped: list[str] = []
        for a in aliases:
            for token in a.split():
                if token not in seen:
                    seen.add(token)
                    deduped.append(token)

        return " ".join(deduped)

    # ── Index management ────────────────────────────────────────────────────

    def rebuild_index(self, registry: "dict[str, ToolMapping]") -> None:
        """Build BMXF field index from the live tool registry.

        Generates retrieval_aliases on each ToolDoc (catalog.py leaves them
        empty), then calls BMXIndex.build_field_index. Safe to call multiple
        times — replaces the previous index on each call.
        """
        snapshot = build_snapshot(registry)

        # Populate retrieval_aliases (scorer-side responsibility)
        for doc in snapshot.docs:
            doc.retrieval_aliases = self._generate_aliases(doc.tool_name, doc.namespace)

        # Build dual indexes from the same ToolDoc set
        env_index = BMXIndex(normalize_scores=True, alpha_override=0.5)
        env_index.build_field_index(snapshot.docs)

        nl_index = BMXIndex(normalize_scores=True, alpha_override=None)
        nl_index.build_field_index(snapshot.docs)

        self._snapshot = snapshot
        self._env_index = env_index
        self._nl_index = nl_index
        # Keep _index pointing at env_index for backward-compat callers
        self._index = env_index
        self._doc_by_key = {doc.tool_key: doc for doc in snapshot.docs}

        logger.debug(
            "BMXFRetriever: rebuilt index for %d tools (snapshot version=%s, hash=%s…)",
            len(snapshot.docs),
            snapshot.version,
            snapshot.schema_hash[:8],
        )

    # ── Version accessor ─────────────────────────────────────────────────────

    def get_snapshot_version(self) -> str:
        """Return the current catalog snapshot version, or empty string if none."""
        return self._snapshot.version if self._snapshot else ""

    # ── Retrieval ───────────────────────────────────────────────────────────

    async def retrieve(
        self,
        context: RetrievalContext,
        candidates: "list[ToolMapping]",
    ) -> list[ScoredTool]:
        """Score candidates using BMXF; in shadow mode return all with scores logged.

        Selects _env_index (alpha_override=0.5) when context.query_mode=="env",
        _nl_index (alpha_override=None) when context.query_mode=="nl".

        If no index has been built yet (or query is empty) falls back to
        returning all candidates with score=1.0 (passthrough behaviour).
        """
        # Select index based on query_mode
        index = self._env_index if context.query_mode == "env" else self._nl_index

        # Fallback: no index or empty query
        if index is None or not context.query.strip():
            return [
                ScoredTool(
                    tool_key=f"{m.server_name}__{m.tool.name}",
                    tool_mapping=m,
                    score=1.0,
                    tier="full",
                )
                for m in candidates
            ]

        # Build key → mapping lookup for the candidate set
        key_to_mapping: dict[str, "ToolMapping"] = {}
        for m in candidates:
            # Reconstruct the namespaced key as stored in tool_to_server
            key = f"{m.server_name}__{m.tool.name}" if m.server_name else m.tool.name
            key_to_mapping[key] = m

        max_k = self._config.max_k if not self._config.shadow_mode else len(candidates)
        raw_scores = index.search_fields(context.query, top_k=max(max_k * 2, 30))

        # Build scored list restricted to the candidate set
        scored: list[ScoredTool] = []
        seen_keys: set[str] = set()

        for chunk_id, score in raw_scores:
            if chunk_id not in key_to_mapping:
                continue
            seen_keys.add(chunk_id)
            scored.append(
                ScoredTool(
                    tool_key=chunk_id,
                    tool_mapping=key_to_mapping[chunk_id],
                    score=score,
                    tier="full",
                )
            )

        # Append unscored candidates (zero relevance signal) at the end
        for key, mapping in key_to_mapping.items():
            if key not in seen_keys:
                scored.append(
                    ScoredTool(
                        tool_key=key,
                        tool_mapping=mapping,
                        score=0.0,
                        tier="full",
                    )
                )

        if self._config.shadow_mode:
            # Shadow mode: score but return all candidates unchanged
            logger.debug(
                "BMXFRetriever shadow: query=%r top_scored=%s/%d",
                context.query,
                len([s for s in scored if s.score > 0]),
                len(scored),
            )
            return scored

        # Live mode: return top max_k
        return scored[:max_k]
