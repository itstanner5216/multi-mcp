"""Telemetry subpackage — allowlisted root scanning for workspace fingerprinting."""
from .evidence import RootEvidence, WorkspaceEvidence, merge_evidence
from .scanner import TelemetryScanner, scan_roots

__all__ = [
    "RootEvidence",
    "WorkspaceEvidence",
    "merge_evidence",
    "TelemetryScanner",
    "scan_roots",
]
