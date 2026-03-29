"""Allowlisted filesystem scanner for MCP roots.

Safety invariants:
- Never reads .env*, *.pem, *.key, id_rsa, id_ed25519, or credential files
- Never follows symlinks outside declared root
- Max depth 6, max 10K entries per root
- 150ms hard timeout per root (partial_scan=True on expiry)
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .evidence import RootEvidence, WorkspaceEvidence, merge_evidence
from .tokens import (
    build_tokens,
    MANIFEST_LANGUAGE_MAP,
    LOCKFILE_NAMES,
    MAX_README_TOKENS,
)

# ── Allowlist ────────────────────────────────────────────────────────────────
ALLOWED_MANIFESTS: frozenset[str] = frozenset(MANIFEST_LANGUAGE_MAP.keys())
ALLOWED_LOCKFILES: frozenset[str] = frozenset(LOCKFILE_NAMES)
ALLOWED_CI_FILES: frozenset[str] = frozenset({
    ".travis.yml", "Jenkinsfile", ".circleci", "azure-pipelines.yml",
    "Makefile",
})
ALLOWED_CONTAINER_FILES: frozenset[str] = frozenset({
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
})
ALLOWED_INFRA_FILES: frozenset[str] = frozenset({
    "terraform.tf", "main.tf", "variables.tf", "cloudformation.yaml",
})
ALLOWED_DB_FILES: frozenset[str] = frozenset({
    "schema.prisma", "schema.sql",
})

import re as _re
README_PATTERN: _re.Pattern = _re.compile(r"^readme(\.(md|rst|txt))?$", _re.IGNORECASE)

ALL_ALLOWED_FILES: frozenset[str] = (
    ALLOWED_MANIFESTS | ALLOWED_LOCKFILES | ALLOWED_CI_FILES |
    ALLOWED_CONTAINER_FILES | ALLOWED_INFRA_FILES | ALLOWED_DB_FILES
)

# ── Denylist ─────────────────────────────────────────────────────────────────
DENIED_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
    "id_dsa", "id_ecdsa",
    "*.aws_credentials", "credentials", ".aws",
    "*.secret", "*.secrets",
)

# ── Scan budgets ─────────────────────────────────────────────────────────────
MAX_DEPTH: int = 6
MAX_ENTRIES: int = 10_000
HARD_TIMEOUT_MS: int = 150


def _is_denied(name: str) -> bool:
    """Return True if the filename matches any denied pattern."""
    for pattern in DENIED_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            return True
    return False


def _uri_to_path(uri: str) -> Optional[Path]:
    """Convert file:// URI or plain path string to Path. Returns None on failure."""
    try:
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            return Path(parsed.path)
        return Path(uri)
    except Exception:
        return None


def scan_root(
    root_uri: str,
    root_name: Optional[str] = None,
    timeout_ms: int = HARD_TIMEOUT_MS,
    max_entries: int = MAX_ENTRIES,
    max_depth: int = MAX_DEPTH,
) -> RootEvidence:
    """Scan a single declared MCP root and return typed sparse tokens.

    Args:
        root_uri: file:// URI or path string of the root to scan.
        root_name: Optional human-readable root name.
        timeout_ms: Hard timeout in milliseconds. Sets partial_scan=True on expiry.
        max_entries: Maximum directory entries to visit. Sets partial_scan=True.
        max_depth: Maximum directory depth to descend.

    Returns:
        RootEvidence with typed sparse tokens, confidence score, and scan metadata.
        partial_scan=True if the scan was cut short by timeout or entry budget.
    """
    root_path = _uri_to_path(root_uri)
    evidence = RootEvidence(
        root_uri=root_uri,
        root_name=root_name,
        tokens={},
        features={},
        confidence=0.0,
        fingerprint_hash="",
        partial_scan=False,
    )

    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return evidence

    deadline = time.monotonic() + timeout_ms / 1000.0
    found_files: set[str] = set()
    readme_lines: list[str] = []
    entries_visited = 0
    partial = False

    def _walk(path: Path, depth: int) -> None:
        nonlocal entries_visited, partial, readme_lines

        if depth > max_depth:
            return
        if time.monotonic() >= deadline:
            partial = True
            return

        try:
            entries = list(path.iterdir())
        except PermissionError:
            return
        except OSError:
            return

        for entry in entries:
            if time.monotonic() >= deadline:
                partial = True
                return
            if entries_visited >= max_entries:
                partial = True
                return

            entries_visited += 1
            name = entry.name

            # Skip symlinks to prevent escape from root
            if entry.is_symlink():
                continue

            # Skip denied files immediately
            if _is_denied(name):
                continue

            rel_path = str(entry.relative_to(root_path))

            if entry.is_file():
                if name in ALL_ALLOWED_FILES:
                    found_files.add(rel_path)
                elif README_PATTERN.match(name) and not readme_lines:
                    # Read first 40 lines of README
                    try:
                        with open(entry, encoding="utf-8", errors="ignore") as f:
                            readme_lines = [f.readline() for _ in range(40)]
                    except OSError:
                        pass

            elif entry.is_dir():
                # Special: .github/workflows directory — add as CI signal
                if rel_path in {".github/workflows", ".github"} or name in {
                    ".github", ".circleci", "migrations",
                }:
                    found_files.add(rel_path)
                _walk(entry, depth + 1)

    _walk(root_path, depth=0)

    if partial:
        evidence.partial_scan = True

    # Build tokens from found files
    tokens = build_tokens(found_files, readme_lines if readme_lines else None)
    evidence.tokens = tokens

    # Compute confidence: 0.0 if no tokens, scales with token family diversity
    # Confidence = min(1.0, unique_families / 3) — 3 distinct families = full confidence
    if tokens:
        families = {tok.split(":")[0] for tok in tokens}
        evidence.confidence = min(1.0, len(families) / 3.0)

    # Stable fingerprint hash from sorted found files
    canonical = str(sorted(found_files))
    evidence.fingerprint_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]

    return evidence


class TelemetryScanner:
    """Scans declared MCP roots and produces WorkspaceEvidence.

    This is the single entry point used by the retrieval pipeline at session init.
    Each root is scanned independently; results are merged into WorkspaceEvidence.
    """

    def __init__(
        self,
        timeout_ms: int = HARD_TIMEOUT_MS,
        max_entries: int = MAX_ENTRIES,
        max_depth: int = MAX_DEPTH,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.max_entries = max_entries
        self.max_depth = max_depth

    def scan_roots(
        self,
        root_uris: list[str],
        root_names: Optional[list[Optional[str]]] = None,
    ) -> WorkspaceEvidence:
        """Scan all declared roots and merge into WorkspaceEvidence.

        Args:
            root_uris: List of file:// URIs or path strings for roots.
            root_names: Optional list of human-readable root names (same length as uris).

        Returns:
            WorkspaceEvidence with merged tokens from all roots.
        """
        names = root_names or [None] * len(root_uris)
        results: list[RootEvidence] = []
        for uri, name in zip(root_uris, names):
            evidence = scan_root(
                uri,
                root_name=name,
                timeout_ms=self.timeout_ms,
                max_entries=self.max_entries,
                max_depth=self.max_depth,
            )
            results.append(evidence)
        return merge_evidence(results)


def scan_roots(
    root_uris: list[str],
    root_names: Optional[list[Optional[str]]] = None,
    timeout_ms: int = HARD_TIMEOUT_MS,
) -> WorkspaceEvidence:
    """Module-level convenience wrapper for TelemetryScanner.scan_roots()."""
    scanner = TelemetryScanner(timeout_ms=timeout_ms)
    return scanner.scan_roots(root_uris, root_names)
