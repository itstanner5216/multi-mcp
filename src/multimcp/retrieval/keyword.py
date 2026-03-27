"""Improved TF-IDF keyword retriever for tool scoring.

Scores tools by relevance using sublinear TF, Lucene-style IDF, cosine
similarity, field-weighted scoring (name/description/parameters), and
query coverage bonuses. Uses inverted index for O(query_terms × posting_list)
search instead of O(query_terms × all_docs).

Improvements over the original keyword.py:
─────────────────────────────────────────
1. SUBLINEAR TF: Uses 1 + log(tf) instead of raw tf/doc_len.
   Prevents high-frequency terms from dominating — a tool mentioning
   "search" 10× scores ~1.3x more than 1×, not 10×.

2. LUCENE-STYLE IDF: log((N - df + 0.5) / (df + 0.5) + 1) instead of
   log((N+1)/(df+1)) + 1. Zero-discriminative terms (appearing in all docs)
   produce near-zero IDF, matching the BMX/BM25 formula for consistency.

3. COSINE NORMALIZATION: TF-IDF vectors are L2-normalized per document,
   making scores length-independent. Short tool names and long descriptions
   are scored on the same scale without ad-hoc length division.

4. THREE-FIELD INDEXING: Indexes tool_name, description, AND inputSchema
   parameter names. Parameter keys like "owner", "repo", "branch" are
   high-signal discriminators that the original missed entirely.

5. CONFIGURABLE FIELD WEIGHTS: name(3.0) > parameters(1.5) > description(1.0)
   reflecting that name matches are the strongest signal, parameter names
   are domain-specific, and description matches are supporting evidence.

6. QUERY COVERAGE BONUS: Documents matching more unique query terms get a
   fractional bonus (coverage_ratio × coverage_weight). Matching 4/4 query
   terms scores higher than 1/4 even if the single match has high TF-IDF.

7. INVERTED INDEX: Posting lists map each term → set of tool_keys containing
   that term. Query evaluation only scores tools with at least one matching
   term, skipping the rest entirely.

8. NO SCORE CLIPPING: Boost is applied multiplicatively and scores are NOT
   capped at 1.0 — ranking signal is preserved. Scores represent relative
   relevance, not absolute probabilities.

Drop-in compatible: same class interface (ToolRetriever ABC), same
rebuild_index(registry) pattern, same retrieve() signature.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Optional

from .base import ToolRetriever
from .models import RetrievalConfig, RetrievalContext, ScoredTool
from .namespace_filter import compute_namespace_boosts

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping

# ── Stopwords ──────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "this", "that", "it", "its", "as", "if", "not", "no", "do", "does",
    "can", "will", "has", "have", "had", "may", "might", "should", "would",
    "all", "each", "every", "any", "some",
})

# ── Scoring constants ──────────────────────────────────────────────────

_FIELD_WEIGHTS = {
    "name": 3.0,
    "description": 1.0,
    "parameters": 1.5,
}
_COVERAGE_WEIGHT = 0.15  # Bonus multiplier for query coverage fraction


# ── Tokenizer ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, splitting on _ and non-alpha."""
    words = re.split(r"[_\W]+", text.lower())
    return [w for w in words if w and w not in _STOPWORDS and len(w) > 1]


# ── Schema parameter extraction ────────────────────────────────────────

def _extract_param_names(schema: object) -> list[str]:
    """Extract parameter names from a tool's inputSchema."""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        return []
    tokens: list[str] = []
    for key in props:
        tokens.extend(_tokenize(str(key)))
    return tokens


class KeywordRetriever(ToolRetriever):
    """Improved TF-IDF retriever with sublinear TF, cosine normalization,
    three-field indexing, and query coverage bonus."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config

        # Per-tool field tokens: {tool_key: {"name": [...], "description": [...], "parameters": [...]}}
        self._tool_tokens: dict[str, dict[str, list[str]]] = {}

        # IDF scores: {term: idf_score}
        self._idf: dict[str, float] = {}

        # Inverted index: {term: set(tool_keys)}
        self._posting: dict[str, set[str]] = {}

        # Precomputed L2 norms per tool per field: {tool_key: {field: norm}}
        self._doc_norms: dict[str, dict[str, float]] = {}

        self._num_tools: int = 0

    # ── Index lifecycle ────────────────────────────────────────────────

    def rebuild_index(self, registry: dict[str, "ToolMapping"]) -> None:
        """Rebuild the TF-IDF index from the current tool registry."""
        self._tool_tokens.clear()
        self._idf.clear()
        self._posting.clear()
        self._doc_norms.clear()
        self._num_tools = len(registry)

        if not registry:
            return

        # ── Pass 1: tokenize each tool across all fields ──
        doc_freq: Counter = Counter()

        for key, mapping in registry.items():
            name_tokens = _tokenize(mapping.tool.name)
            desc_tokens = _tokenize(mapping.tool.description or "")
            param_tokens = _extract_param_names(mapping.tool.inputSchema)

            self._tool_tokens[key] = {
                "name": name_tokens,
                "description": desc_tokens,
                "parameters": param_tokens,
            }

            # Document frequency: unique terms across ALL fields for this tool
            all_terms = set(name_tokens) | set(desc_tokens) | set(param_tokens)
            for term in all_terms:
                doc_freq[term] += 1

            # Build posting list
            for term in all_terms:
                if term not in self._posting:
                    self._posting[term] = set()
                self._posting[term].add(key)

        # ── Pass 2: compute IDF (Lucene variant) ──
        n = self._num_tools
        for term, df in doc_freq.items():
            self._idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

        # ── Pass 3: precompute per-field L2 norms ──
        for key, fields in self._tool_tokens.items():
            norms: dict[str, float] = {}
            for field_name, tokens in fields.items():
                if not tokens:
                    norms[field_name] = 0.0
                    continue
                tf_counter = Counter(tokens)
                sq_sum = 0.0
                for term, raw_tf in tf_counter.items():
                    w = (1.0 + math.log(raw_tf)) * self._idf.get(term, 0.0)
                    sq_sum += w * w
                norms[field_name] = math.sqrt(sq_sum) if sq_sum > 0 else 0.0
            self._doc_norms[key] = norms

    # ── Retrieval ──────────────────────────────────────────────────────

    async def retrieve(
        self,
        context: RetrievalContext,
        candidates: list["ToolMapping"],
    ) -> list[ScoredTool]:
        """Score candidates against the context query using improved TF-IDF."""
        query_tokens = _tokenize(context.query)

        # Build candidate key lookup
        candidate_keys: set[str] = set()
        key_to_mapping: dict[str, "ToolMapping"] = {}
        for m in candidates:
            key = f"{m.server_name}__{m.tool.name}"
            candidate_keys.add(key)
            key_to_mapping[key] = m

        # Compute namespace boosts
        boosts = compute_namespace_boosts(
            {k: key_to_mapping[k] for k in candidate_keys if k in key_to_mapping},
            server_hint=context.server_hint,
        )

        # Empty query: return all candidates with uniform score
        if not query_tokens:
            scored = [
                ScoredTool(
                    tool_key=key,
                    tool_mapping=key_to_mapping[key],
                    score=0.5,
                    tier="full",
                )
                for key in candidate_keys
                if key in self._tool_tokens
            ]
            scored.sort(key=lambda s: s.score, reverse=True)
            return scored[:self._config.top_k]

        # ── Identify candidate tools via posting lists ──
        matching_keys: set[str] = set()
        for qt in query_tokens:
            posting = self._posting.get(qt)
            if posting:
                matching_keys.update(posting & candidate_keys)

        # ── Score matching tools ──
        unique_query_terms = set(query_tokens)
        scored: list[ScoredTool] = []

        for key in matching_keys:
            fields = self._tool_tokens.get(key)
            if fields is None:
                continue

            # Weighted field score
            total_score = 0.0
            total_weight = 0.0
            matched_terms: set[str] = set()

            for field_name, weight in _FIELD_WEIGHTS.items():
                doc_tokens = fields.get(field_name, [])
                if not doc_tokens:
                    continue

                field_score, field_matched = self._score_field(
                    query_tokens, doc_tokens, key, field_name,
                )
                total_score += weight * field_score
                total_weight += weight
                matched_terms.update(field_matched)

            if total_weight > 0:
                total_score /= total_weight

            # Query coverage bonus: reward tools matching more unique query terms
            if unique_query_terms:
                coverage = len(matched_terms) / len(unique_query_terms)
                total_score *= (1.0 + _COVERAGE_WEIGHT * coverage)

            # Apply namespace boost (no capping)
            boost = boosts.get(key, 1.0)
            total_score *= boost

            if total_score > 0:
                scored.append(ScoredTool(
                    tool_key=key,
                    tool_mapping=key_to_mapping[key],
                    score=total_score,
                    tier="full",
                ))

        # Sort by score descending, take top-k
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:self._config.top_k]

    # ── Field scoring ──────────────────────────────────────────────────

    def _score_field(
        self,
        query_tokens: list[str],
        doc_tokens: list[str],
        tool_key: str,
        field_name: str,
    ) -> tuple[float, set[str]]:
        """Compute cosine similarity between query and a single field's tokens.

        Uses sublinear TF (1 + log(tf)) × IDF for both query and document,
        with L2-normalized document vectors (precomputed).

        Returns:
            Tuple of (similarity score, set of matched query terms).
        """
        if not doc_tokens or not query_tokens:
            return 0.0, set()

        doc_tf = Counter(doc_tokens)
        query_tf = Counter(query_tokens)

        doc_norm = self._doc_norms.get(tool_key, {}).get(field_name, 0.0)
        if doc_norm == 0.0:
            return 0.0, set()

        # Compute dot product: Σ (query_weight × doc_weight)
        dot = 0.0
        q_sq_sum = 0.0
        matched: set[str] = set()

        for qt, q_raw_tf in query_tf.items():
            idf = self._idf.get(qt, 0.0)
            if idf <= 0:
                continue

            q_weight = (1.0 + math.log(q_raw_tf)) * idf
            q_sq_sum += q_weight * q_weight

            d_raw_tf = doc_tf.get(qt, 0)
            if d_raw_tf > 0:
                d_weight = (1.0 + math.log(d_raw_tf)) * idf
                dot += q_weight * d_weight
                matched.add(qt)

        if dot == 0.0:
            return 0.0, matched

        # Cosine similarity = dot / (|q| × |d|)
        q_norm = math.sqrt(q_sq_sum) if q_sq_sum > 0 else 0.0
        if q_norm == 0.0:
            return 0.0, matched

        similarity = dot / (q_norm * doc_norm)
        return min(similarity, 1.0), matched
