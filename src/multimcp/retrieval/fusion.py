"""Reciprocal Rank Fusion and alpha-decay blending for turn-by-turn tool ranking."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .models import ScoredTool

if TYPE_CHECKING:
    pass

RRF_K = 10


def weighted_rrf(
    env_ranked: list[ScoredTool],
    conv_ranked: list[ScoredTool],
    alpha: float,
) -> list[ScoredTool]:
    """Fuse environment and conversation rankings via weighted RRF.

    score(tool) = alpha / (RRF_K + rank_env) + (1-alpha) / (RRF_K + rank_conv)

    Tools absent from a list are penalized with max_rank (len of that list + 1).
    Returns list sorted by descending fused score.
    """
    if not env_ranked and not conv_ranked:
        return []

    env_ranks = {t.tool_key: i + 1 for i, t in enumerate(env_ranked)}
    conv_ranks = {t.tool_key: i + 1 for i, t in enumerate(conv_ranked)}
    all_keys = set(env_ranks) | set(conv_ranks)

    # Penalty rank for tools absent from a list
    env_max = len(env_ranked) + 1
    conv_max = len(conv_ranked) + 1
    conv_max = len(conv_ranked)

    # Collect tool_mapping references: env takes precedence, conv fills gaps
    tool_map: dict[str, object] = {}
    for t in env_ranked:
        tool_map[t.tool_key] = t.tool_mapping
    for t in conv_ranked:
        tool_map.setdefault(t.tool_key, t.tool_mapping)

    fused: list[ScoredTool] = []
    for key in all_keys:
        env_r = env_ranks.get(key, env_max)
        conv_r = conv_ranks.get(key, conv_max)
        score = alpha / (RRF_K + env_r) + (1 - alpha) / (RRF_K + conv_r)
        fused.append(
            ScoredTool(
                tool_key=key,
                tool_mapping=tool_map[key],  # type: ignore[arg-type]
                score=score,
                tier="full",
            )
        )

    fused.sort(key=lambda s: (-s.score, s.tool_key))
    return fused


def compute_alpha(
    turn: int,
    workspace_confidence: float,
    conv_confidence: float,
    roots_changed: bool = False,
    explicit_tool_mention: bool = False,
) -> float:
    """Compute alpha blending weight for RRF fusion.

    Alpha = weight given to environment ranking. High alpha -> env-dominated.
    Decays from 0.85 at turn 0 to floor of 0.15 at turn 10+.

    Overrides:
      - Low workspace confidence (<0.45): reduce base by 0.20
      - Explicit tool name mention with high conv confidence: snap to 0.15
      - Roots changed since last turn: reset to >=0.80
    """
    base = max(0.15, 0.85 * math.exp(-0.25 * turn))

    if workspace_confidence < 0.45:
        base = max(0.15, base - 0.20)

    if explicit_tool_mention and conv_confidence >= 0.70:
        base = 0.15

    if roots_changed:
        base = max(base, 0.80)

    return base
