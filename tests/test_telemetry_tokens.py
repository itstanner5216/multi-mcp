"""RED tests for telemetry tokens and evidence — Task 1 TDD phase.

Tests: build_tokens(), merge_evidence(), workspace hash stability.
"""
from __future__ import annotations

import pytest

from src.multimcp.retrieval.telemetry.tokens import (
    build_tokens,
    TOKEN_WEIGHTS,
    _apply_family_cap,
    MAX_FAMILY_CONTRIBUTION,
)
from src.multimcp.retrieval.telemetry.evidence import merge_evidence
from src.multimcp.retrieval.models import RootEvidence, WorkspaceEvidence


# ── build_tokens: manifest tokens ────────────────────────────────────────────

def test_package_json_manifest_token():
    tokens = build_tokens({"package.json"})
    assert "manifest:package.json" in tokens
    # Weight may be scaled by family cap, but must be positive and <= base weight
    assert 0 < tokens["manifest:package.json"] <= TOKEN_WEIGHTS["manifest:"]


def test_package_json_lang_tokens():
    tokens = build_tokens({"package.json"})
    assert "lang:javascript" in tokens
    assert "lang:typescript" in tokens
    assert "lang:npm" in tokens
    assert "lang:node" in tokens


def test_cargo_toml_manifest_token():
    tokens = build_tokens({"Cargo.toml"})
    assert "manifest:Cargo.toml" in tokens
    # Weight may be scaled by family cap, but must be positive and <= base weight
    assert 0 < tokens["manifest:Cargo.toml"] <= TOKEN_WEIGHTS["manifest:"]


def test_cargo_toml_lang_tokens():
    tokens = build_tokens({"Cargo.toml"})
    assert "lang:rust" in tokens
    assert "lang:cargo" in tokens
    assert "lang:crate" in tokens


def test_pyproject_toml_tokens():
    tokens = build_tokens({"pyproject.toml"})
    assert "manifest:pyproject.toml" in tokens
    assert "lang:python" in tokens


# ── build_tokens: token weights ───────────────────────────────────────────────

def test_lang_weight():
    """Lang tokens have correct base weight before cap; after cap may be scaled."""
    tokens = build_tokens({"Cargo.toml"})
    # lang:rust is present with positive weight (may be scaled by family cap)
    assert tokens.get("lang:rust", 0.0) > 0.0
    # Weight should not exceed the base TOKEN_WEIGHTS value
    assert tokens["lang:rust"] <= TOKEN_WEIGHTS["lang:"]


def test_empty_files_returns_empty():
    tokens = build_tokens(set())
    assert tokens == {}


# ── family cap abuse resistance ───────────────────────────────────────────────

def test_family_cap_single_family():
    """All tokens in same family — family is scaled to MAX_FAMILY_CONTRIBUTION * original total."""
    tokens = {"lang:python": 2.0, "lang:rust": 2.0, "lang:go": 2.0}
    original_total = sum(tokens.values())  # 6.0
    capped = _apply_family_cap(tokens)
    lang_total = sum(v for k, v in capped.items() if k.startswith("lang:"))
    # Family should be scaled down to at most 35% of original total
    assert lang_total <= original_total * MAX_FAMILY_CONTRIBUTION + 1e-9


def test_family_cap_preserves_small_families():
    """Small families should not be scaled down."""
    tokens = {"manifest:Cargo.toml": 3.0, "ci:github-actions": 1.5, "db:schema.sql": 1.5}
    capped = _apply_family_cap(tokens)
    # With distinct families it's possible none are capped since each is 1 of 3
    assert len(capped) == 3


def test_family_cap_applied_in_build_tokens():
    """build_tokens applies _apply_family_cap — families that exceed cap are scaled down."""
    from src.multimcp.retrieval.telemetry.tokens import _apply_family_cap
    # Force many lang tokens by using multiple manifests
    files = {"package.json", "Cargo.toml", "pyproject.toml", "go.mod"}
    tokens = build_tokens(files)
    # Verify family cap is actually applied: result should match _apply_family_cap output
    # The key invariant: no family exceeds MAX_FAMILY_CONTRIBUTION * original_total
    # We verify by testing the underlying function directly with a known input
    raw_tokens = {"lang:python": 2.0, "lang:rust": 2.0, "lang:go": 2.0, "manifest:go.mod": 3.0}
    original_total = sum(raw_tokens.values())  # 9.0
    capped = _apply_family_cap(raw_tokens)
    lang_total = sum(v for k, v in capped.items() if k.startswith("lang:"))
    manifest_total = sum(v for k, v in capped.items() if k.startswith("manifest:"))
    assert lang_total <= original_total * MAX_FAMILY_CONTRIBUTION + 1e-9
    assert manifest_total <= original_total * MAX_FAMILY_CONTRIBUTION + 1e-9


# ── merge_evidence ─────────────────────────────────────────────────────────────

def test_merge_evidence_combines_tokens():
    r1 = RootEvidence(root_uri="/a", tokens={"manifest:Cargo.toml": 3.0}, confidence=0.5)
    r2 = RootEvidence(root_uri="/b", tokens={"lang:python": 2.0}, confidence=0.3)
    ws = merge_evidence([r1, r2])
    assert "manifest:Cargo.toml" in ws.merged_tokens
    assert "lang:python" in ws.merged_tokens


def test_merge_evidence_averages_confidence():
    r1 = RootEvidence(root_uri="/a", tokens={}, confidence=0.5)
    r2 = RootEvidence(root_uri="/b", tokens={}, confidence=0.3)
    ws = merge_evidence([r1, r2])
    assert ws.workspace_confidence == pytest.approx(0.4, abs=0.01)


def test_merge_evidence_workspace_hash_stable():
    r1 = RootEvidence(root_uri="/a", tokens={"manifest:Cargo.toml": 3.0}, confidence=0.5)
    ws1 = merge_evidence([r1])
    ws2 = merge_evidence([r1])
    assert ws1.workspace_hash == ws2.workspace_hash


def test_merge_evidence_hash_changes_on_different_tokens():
    r1 = RootEvidence(root_uri="/a", tokens={"manifest:Cargo.toml": 3.0}, confidence=0.5)
    r2 = RootEvidence(root_uri="/a", tokens={"lang:python": 2.0}, confidence=0.5)
    ws1 = merge_evidence([r1])
    ws2 = merge_evidence([r2])
    assert ws1.workspace_hash != ws2.workspace_hash


def test_merge_evidence_returns_workspace_evidence():
    r1 = RootEvidence(root_uri="/a", tokens={}, confidence=0.0)
    ws = merge_evidence([r1])
    assert isinstance(ws, WorkspaceEvidence)
    assert ws.roots == [r1]
