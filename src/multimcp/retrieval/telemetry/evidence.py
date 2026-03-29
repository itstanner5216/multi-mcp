"""Re-exports and workspace evidence merge utilities."""
from __future__ import annotations

import hashlib
import json

from ..models import RootEvidence, WorkspaceEvidence


def merge_evidence(roots: list[RootEvidence]) -> WorkspaceEvidence:
    """Merge per-root evidence into a single WorkspaceEvidence."""
    merged: dict[str, float] = {}
    for root in roots:
        for tok, weight in root.tokens.items():
            merged[tok] = merged.get(tok, 0.0) + weight
    confidence = sum(r.confidence for r in roots) / max(len(roots), 1)
    canonical = json.dumps(sorted(merged.items()), sort_keys=True)
    workspace_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return WorkspaceEvidence(
        roots=roots,
        workspace_confidence=confidence,
        merged_tokens=merged,
        workspace_hash=workspace_hash,
    )


__all__ = ["RootEvidence", "WorkspaceEvidence", "merge_evidence"]
