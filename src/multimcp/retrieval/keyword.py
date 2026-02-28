"""TF-IDF keyword retriever for tool scoring.

Scores tools by relevance using term frequency-inverse document frequency on
tool names and descriptions. Uses only stdlib — no numpy/sklearn.
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

# Common English stopwords
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "this", "that", "it", "its", "as", "if", "not", "no", "do", "does",
    "can", "will", "has", "have", "had", "may", "might", "should", "would",
    "all", "each", "every", "any", "some",
})

# Name token weight multiplier (name matches are 2x more important than description)
_NAME_WEIGHT = 2.0


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, splitting on _ and non-alpha."""
    words = re.split(r"[_\W]+", text.lower())
    return [w for w in words if w and w not in _STOPWORDS and len(w) > 1]


class KeywordRetriever(ToolRetriever):
    """TF-IDF-inspired retriever scoring tools by keyword relevance."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config
        # Per-tool token lists: {tool_key: {"name_tokens": [...], "desc_tokens": [...]}}
        self._tool_tokens: dict[str, dict[str, list[str]]] = {}
        # IDF scores: {term: idf_score}
        self._idf: dict[str, float] = {}
        self._num_tools: int = 0

    def rebuild_index(self, registry: dict[str, "ToolMapping"]) -> None:
        """Rebuild the TF-IDF index from the current tool registry."""
        self._tool_tokens.clear()
        self._idf.clear()
        self._num_tools = len(registry)

        if not registry:
            return

        # Tokenize each tool
        doc_freq: Counter = Counter()
        for key, mapping in registry.items():
            name_tokens = _tokenize(mapping.tool.name)
            desc_tokens = _tokenize(mapping.tool.description or "")
            self._tool_tokens[key] = {
                "name_tokens": name_tokens,
                "desc_tokens": desc_tokens,
            }
            # Document frequency: count unique terms per tool
            unique_terms = set(name_tokens) | set(desc_tokens)
            for term in unique_terms:
                doc_freq[term] += 1

        # Compute IDF: log(N / df) — terms in fewer docs get higher weight
        for term, df in doc_freq.items():
            self._idf[term] = math.log((self._num_tools + 1) / (df + 1)) + 1.0

    async def retrieve(
        self,
        context: RetrievalContext,
        candidates: list["ToolMapping"],
    ) -> list[ScoredTool]:
        """Score candidates against the context query using TF-IDF."""
        query_tokens = _tokenize(context.query)

        # Build candidate key lookup
        candidate_keys = set()
        key_to_mapping: dict[str, "ToolMapping"] = {}
        for m in candidates:
            # Reconstruct the key from server_name + tool name
            key = f"{m.server_name}__{m.tool.name}"
            candidate_keys.add(key)
            key_to_mapping[key] = m

        # Compute namespace boosts
        boosts = compute_namespace_boosts(
            {k: key_to_mapping[k] for k in candidate_keys if k in key_to_mapping},
            server_hint=context.server_hint,
        )

        # Score each candidate
        scored: list[ScoredTool] = []
        for key in candidate_keys:
            tokens = self._tool_tokens.get(key)
            if tokens is None:
                continue

            if not query_tokens:
                # Empty query: all tools score equally
                score = 0.5
            else:
                # TF-IDF scoring
                name_score = self._score_tokens(query_tokens, tokens["name_tokens"])
                desc_score = self._score_tokens(query_tokens, tokens["desc_tokens"])
                score = (_NAME_WEIGHT * name_score + desc_score) / (_NAME_WEIGHT + 1.0)

            # Apply namespace boost
            boost = boosts.get(key, 1.0)
            score = min(score * boost, 1.0)

            scored.append(ScoredTool(
                tool_key=key,
                tool_mapping=key_to_mapping[key],
                score=score,
                tier="full",
            ))

        # Sort by score descending, take top-k
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:self._config.top_k]

    def _score_tokens(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """Compute TF-IDF similarity between query and document tokens."""
        if not doc_tokens or not query_tokens:
            return 0.0

        doc_tf = Counter(doc_tokens)
        doc_len = len(doc_tokens)

        score = 0.0
        for qt in query_tokens:
            if qt in doc_tf:
                tf = doc_tf[qt] / doc_len
                idf = self._idf.get(qt, 1.0)
                score += tf * idf

        # Normalize by query length
        max_possible = sum(self._idf.get(qt, 1.0) for qt in query_tokens)
        if max_possible > 0:
            score /= max_possible

        return min(score, 1.0)
