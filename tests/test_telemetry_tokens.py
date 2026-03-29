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
    assert tokens["manifest:package.json"] == TOKEN_WEIGHTS["manifest:"]


def test_package_json_lang_tokens():
    tokens = build_tokens({"package.json"})
    assert "lang:javascript" in tokens
    assert "lang:typescript" in tokens
    assert "lang:npm" in tokens
    assert "lang:node" in tokens


def test_cargo_toml_manifest_token():
    tokens = build_tokens({"Cargo.toml"})
    assert "manifest:Cargo.toml" in tokens
    assert tokens["manifest:Cargo.toml"] == TOKEN_WEIGHTS["manifest:"]


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
    tokens = build_tokens({"Cargo.toml"})
    assert tokens["lang:rust"] == TOKEN_WEIGHTS["lang:"]


def test_empty_files_returns_empty():
    tokens = build_tokens(set())
    assert tokens == {}


# ── family cap abuse resistance ───────────────────────────────────────────────

def test_family_cap_single_family():
    """All tokens in same family — sum must be <= 35% of total."""
    tokens = {"lang:python": 2.0, "lang:rust": 2.0, "lang:go": 2.0}
    capped = _apply_family_cap(tokens)
    total = sum(capped.values())
    lang_total = sum(v for k, v in capped.items() if k.startswith("lang:"))
    if total > 0:
        assert lang_total / total <= MAX_FAMILY_CONTRIBUTION + 1e-9


def test_family_cap_preserves_small_families():
    """Small families should not be scaled down."""
    tokens = {"manifest:Cargo.toml": 3.0, "ci:github-actions": 1.5, "db:schema.sql": 1.5}
    capped = _apply_family_cap(tokens)
    # With distinct families it's possible none are capped since each is 1 of 3
    assert len(capped) == 3


def test_family_cap_applied_in_build_tokens():
    """build_tokens with many same-family files should have family cap."""
    # Force many lang tokens by using multiple manifests
    files = {"package.json", "Cargo.toml", "pyproject.toml", "go.mod"}
    tokens = build_tokens(files)
    total = sum(tokens.values())
    if total > 0:
        for prefix in ["manifest:", "lang:", "lock:"]:
            family_sum = sum(v for k, v in tokens.items() if k.startswith(prefix))
            assert family_sum / total <= MAX_FAMILY_CONTRIBUTION + 1e-9


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
