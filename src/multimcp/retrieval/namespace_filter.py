"""Namespace pre-filter boost utility.

Prioritizes tools from a hinted server namespace without removing others.
Pure utility — no state, no side effects.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping


def compute_namespace_boosts(
    candidates: dict[str, "ToolMapping"],
    server_hint: Optional[str],
    boost_factor: float = 1.5,
) -> dict[str, float]:
    """Compute per-tool boost factors based on namespace hint.

    Args:
        candidates: Dict of tool_key -> ToolMapping
        server_hint: Server name to boost (e.g., "github"). None = no boost.
        boost_factor: Multiplier for matching tools. Default 1.5.

    Returns:
        Dict of tool_key -> boost_factor (1.0 for non-matching, boost_factor for matching)
    """
    if server_hint is None:
        return {key: 1.0 for key in candidates}

    return {
        key: boost_factor if mapping.server_name == server_hint else 1.0
        for key, mapping in candidates.items()
    }
