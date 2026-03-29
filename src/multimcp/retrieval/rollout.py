"""Deterministic canary session assignment for gradual BMXF rollout.

Session assignment is hash-based: same session_id always maps to the
same canary/control group. This enables consistent per-session behavior
and reproducible metric analysis.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import RetrievalConfig


def is_canary_session(session_id: str, canary_percentage: float) -> bool:
    """Determine whether a session is in the canary cohort.

    Uses SHA-256 hash of session_id to assign a stable bucket [0, 100).
    Returns True if bucket < canary_percentage.

    SHA-256 is used here for deterministic bucket assignment only (not for
    cryptographic security). It provides uniform distribution and is not
    subject to collision concerns relevant to this use case.

    Args:
        session_id: Unique session identifier.
        canary_percentage: 0.0-100.0 range. 0 = all control, 100 = all canary.
    """
    if canary_percentage <= 0.0:
        return False
    if canary_percentage >= 100.0:
        return True
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < canary_percentage


def get_session_group(session_id: str, config: "RetrievalConfig") -> str:
    """Return the rollout group for a session: 'canary' or 'control'.

    Rollout stages:
      - 'shadow': All sessions are 'control' (score but return all tools).
      - 'canary': Hash-based assignment per canary_percentage.
      - 'ga': All sessions are 'canary' (all get BMXF filtering).
    """
    stage = config.rollout_stage
    if stage == "shadow":
        return "control"
    if stage == "ga":
        return "canary"
    # stage == "canary"
    return "canary" if is_canary_session(session_id, config.canary_percentage) else "control"
