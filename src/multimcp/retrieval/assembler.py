"""Two-tier description assembly for token-optimized tool lists.

Full tier: complete description + full inputSchema (top-K tools).
Summary tier: truncated description + simplified schema (remaining tools).
~90% token reduction for summary-tier tools.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from mcp import types

from .models import RetrievalConfig, ScoredTool

_MAX_SUMMARY_CHARS = 80
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _truncate_description(desc: str) -> str:
    """Truncate to first sentence or max chars, whichever is shorter."""
    if not desc or len(desc) <= _MAX_SUMMARY_CHARS:
        return desc

    # Try first sentence
    sentences = _SENTENCE_BOUNDARY.split(desc, maxsplit=1)
    if len(sentences) > 1 and len(sentences[0]) <= _MAX_SUMMARY_CHARS:
        return sentences[0]

    # Fall back to char limit
    return desc[:_MAX_SUMMARY_CHARS].rstrip() + "…"


def _strip_descriptions(schema: Any) -> Any:
    """Recursively strip 'description' fields from schema properties."""
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "description":
            continue  # Strip description at this level
        elif key == "properties" and isinstance(value, dict):
            result[key] = {
                prop_name: _strip_descriptions(prop_val)
                for prop_name, prop_val in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            result[key] = _strip_descriptions(value)
        elif isinstance(value, dict):
            result[key] = _strip_descriptions(value)
        else:
            result[key] = value
    return result


class TieredAssembler:
    """Assembles ranked tools into full/summary tier Tool objects."""

    def assemble(
        self,
        tools: list[ScoredTool],
        config: RetrievalConfig,
    ) -> list[types.Tool]:
        """Create tiered Tool copies from ranked ScoredTools.

        First `config.full_description_count` tools get full descriptions.
        Remaining tools get truncated descriptions and simplified schemas.
        NEVER mutates the original Tool objects in the registry.
        """
        if not tools:
            return []

        result: list[types.Tool] = []
        for i, scored in enumerate(tools):
            original = scored.tool_mapping.tool
            if i < config.full_description_count:
                scored.tier = "full"
                # Full tier: copy as-is
                result.append(
                    types.Tool(
                        name=original.name,
                        description=original.description,
                        inputSchema=copy.deepcopy(original.inputSchema),
                    )
                )
            else:
                scored.tier = "summary"
                # Summary tier: truncate + simplify
                result.append(
                    types.Tool(
                        name=original.name,
                        description=_truncate_description(original.description or ""),
                        inputSchema=_strip_descriptions(
                            copy.deepcopy(original.inputSchema)
                        ),
                    )
                )
        return result
