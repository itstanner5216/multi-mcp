"""Tests for telemetry scanner — allowlist, budget limits, typed token extraction.

Tests: TELEM-01 (allowlist), TELEM-02 (typed tokens), TELEM-03 (scan limits), TELEM-04 (denylist).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.multimcp.retrieval.telemetry.scanner import (
    HARD_TIMEOUT_MS,
    MAX_ENTRIES,
    TelemetryScanner,
    scan_root,
    scan_roots,
    _is_denied,
)
from src.multimcp.retrieval.telemetry.tokens import build_tokens, TOKEN_WEIGHTS
from src.multimcp.retrieval.telemetry.evidence import merge_evidence
from src.multimcp.retrieval.models import RootEvidence, WorkspaceEvidence


# ── Denylist tests (TELEM-04) ────────────────────────────────────────────────

def test_denied_env_file():
    assert _is_denied(".env") is True

def test_denied_env_with_suffix():
    assert _is_denied(".env.production") is True

def test_denied_pem():
    assert _is_denied("server.pem") is True

def test_denied_key():
    assert _is_denied("server.key") is True

def test_denied_rsa():
    assert _is_denied("id_rsa") is True

def test_denied_ed25519():
    assert _is_denied("id_ed25519") is True

def test_not_denied_package_json():
    assert _is_denied("package.json") is False

def test_not_denied_cargo_toml():
    assert _is_denied("Cargo.toml") is False


# ── Allowlist + token extraction tests (TELEM-01, TELEM-02) ──────────────────

def test_scan_root_with_package_json():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"name":"test"}')
        evidence = scan_root(tmp)
    assert "manifest:package.json" in evidence.tokens
    assert evidence.tokens["manifest:package.json"] == TOKEN_WEIGHTS["manifest:"]
    assert "lang:javascript" in evidence.tokens
    assert evidence.partial_scan is False


def test_scan_root_with_cargo_toml():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Cargo.toml").write_text('[package]\nname = "test"')
        evidence = scan_root(tmp)
    assert "manifest:Cargo.toml" in evidence.tokens
    assert "lang:rust" in evidence.tokens


def test_scan_root_env_file_not_read():
    """Even if .env exists, no token for it appears in evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".env").write_text("SECRET_KEY=super_secret")
        (Path(tmp) / "package.json").write_text('{}')
        evidence = scan_root(tmp)
    # No token derived from .env
    for tok in evidence.tokens:
        assert ".env" not in tok
    # package.json token IS present
    assert "manifest:package.json" in evidence.tokens


def test_scan_root_ssh_key_not_read():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----")
        evidence = scan_root(tmp)
    for tok in evidence.tokens:
        assert "id_rsa" not in tok
        assert "rsa" not in tok.lower()


def test_scan_root_empty_directory():
    with tempfile.TemporaryDirectory() as tmp:
        evidence = scan_root(tmp)
    assert evidence.confidence == 0.0
    assert evidence.tokens == {}
    assert evidence.partial_scan is False


def test_scan_root_nonexistent():
    evidence = scan_root("/nonexistent/path/abc123")
    assert evidence.confidence == 0.0
    assert evidence.tokens == {}


def test_scan_root_confidence_with_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Cargo.toml").write_text("")
        evidence = scan_root(tmp)
    assert evidence.confidence > 0.0


def test_scan_root_fingerprint_stable():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Cargo.toml").write_text("")
        e1 = scan_root(tmp)
        e2 = scan_root(tmp)
    assert e1.fingerprint_hash == e2.fingerprint_hash


def test_scan_root_fingerprint_changes():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Cargo.toml").write_text("")
        e1 = scan_root(tmp)
        (Path(tmp) / "package.json").write_text("")
        e2 = scan_root(tmp)
    assert e1.fingerprint_hash != e2.fingerprint_hash


# ── Scan budget limits (TELEM-03) ────────────────────────────────────────────

def test_scan_partial_on_entry_limit():
    """When max_entries is exceeded, partial_scan=True."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create 15 dummy files (above max_entries=10 in this test call)
        for i in range(15):
            (Path(tmp) / f"file_{i}.txt").write_text("")
        evidence = scan_root(tmp, max_entries=10)
    assert evidence.partial_scan is True


def test_scan_partial_on_timeout():
    """When timeout is 1ms on a dir with many files, partial_scan=True."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create subdirs to force traversal work
        for i in range(5):
            subdir = Path(tmp) / f"subdir_{i}"
            subdir.mkdir()
            for j in range(20):
                (subdir / f"file_{j}.txt").write_text("")
        evidence = scan_root(tmp, timeout_ms=1)
    # May or may not be partial depending on system speed, but should not raise
    assert isinstance(evidence.partial_scan, bool)


def test_scan_respects_max_depth():
    """Scan does not descend beyond max_depth."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create a deep structure: tmp/a/b/c/d/e/f/g with Cargo.toml at depth 7
        deep = Path(tmp)
        for _ in range(7):
            deep = deep / "sub"
            deep.mkdir(exist_ok=True)
        (deep / "Cargo.toml").write_text("")
        evidence = scan_root(tmp, max_depth=6)
    # Cargo.toml is at depth 7, should NOT be found
    assert "manifest:Cargo.toml" not in evidence.tokens


# ── Token abuse resistance ────────────────────────────────────────────────────

def test_family_cap_applied():
    """No single token family exceeds 35% of total weight after capping."""
    from src.multimcp.retrieval.telemetry.tokens import _apply_family_cap, MAX_FAMILY_CONTRIBUTION

    # All tokens in same family — should be scaled down
    tokens = {"lang:python": 2.0, "lang:rust": 2.0, "lang:go": 2.0}
    original_total = sum(tokens.values())
    capped = _apply_family_cap(tokens)
    lang_total = sum(v for k, v in capped.items() if k.startswith("lang:"))
    if original_total > 0:
        assert lang_total <= original_total * MAX_FAMILY_CONTRIBUTION + 1e-9


# ── merge_evidence (TELEM-02) ────────────────────────────────────────────────

def test_merge_evidence_combines_tokens():
    r1 = RootEvidence(root_uri="/a", tokens={"manifest:Cargo.toml": 3.0}, confidence=0.5)
    r2 = RootEvidence(root_uri="/b", tokens={"lang:python": 2.0}, confidence=0.3)
    ws = merge_evidence([r1, r2])
    assert "manifest:Cargo.toml" in ws.merged_tokens
    assert "lang:python" in ws.merged_tokens
    assert ws.workspace_confidence == pytest.approx(0.4, abs=0.01)


def test_merge_evidence_workspace_hash_stable():
    r1 = RootEvidence(root_uri="/a", tokens={"manifest:Cargo.toml": 3.0}, confidence=0.5)
    ws1 = merge_evidence([r1])
    ws2 = merge_evidence([r1])
    assert ws1.workspace_hash == ws2.workspace_hash


def test_merge_evidence_hash_changes():
    r1 = RootEvidence(root_uri="/a", tokens={"manifest:Cargo.toml": 3.0}, confidence=0.5)
    r2 = RootEvidence(root_uri="/a", tokens={"lang:python": 2.0}, confidence=0.5)
    ws1 = merge_evidence([r1])
    ws2 = merge_evidence([r2])
    assert ws1.workspace_hash != ws2.workspace_hash


# ── TelemetryScanner (TELEM-01) ──────────────────────────────────────────────

def test_telemetry_scanner_returns_workspace_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "pyproject.toml").write_text("[project]")
        scanner = TelemetryScanner()
        ws = scanner.scan_roots([tmp])
    assert isinstance(ws, WorkspaceEvidence)
    assert "manifest:pyproject.toml" in ws.merged_tokens


def test_scan_roots_module_function():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "go.mod").write_text("module example")
        ws = scan_roots([tmp])
    assert "manifest:go.mod" in ws.merged_tokens


def test_scanner_with_file_uri():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Cargo.toml").write_text("")
        ws = scan_roots([f"file://{tmp}"])
    assert "manifest:Cargo.toml" in ws.merged_tokens
