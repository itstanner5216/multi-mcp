"""Relevance ranker with specificity-based tiebreaking.

Ranks tools by score (descending) with most-specific-first tiebreaking
for tools with similar scores. Exploits LLM primacy bias (1.3-3.4x).
"""

from __future__ import annotations

from .models import ScoredTool

# Scores within this tolerance are considered tied
_SCORE_TOLERANCE = 0.05


def _get_specificity(scored: ScoredTool) -> int:
    """Count input properties as a specificity proxy."""
    schema = scored.tool_mapping.tool.inputSchema
    if isinstance(schema, dict):
        props = schema.get("properties", {})
        if isinstance(props, dict):
            return len(props)
    return 0


class RelevanceRanker:
    """Ranks scored tools by relevance with specificity tiebreaking."""

    def rank(self, tools: list[ScoredTool]) -> list[ScoredTool]:
        """Rank tools by score descending, tiebreak by specificity descending.

        Two tools are "tied" if their scores differ by less than SCORE_TOLERANCE.
        Among tied tools, the one with more inputSchema properties ranks first.
        """
        if not tools:
            return []

        return sorted(
            tools,
            key=lambda t: (
                # Bucket scores into tolerance bands for tiebreaking
                round(t.score / _SCORE_TOLERANCE) * _SCORE_TOLERANCE,
                # Within a band, more specific tools rank first
                _get_specificity(t),
                # Final tiebreak: tool_key for determinism
                t.tool_key,
            ),
            reverse=True,
        )
