"""Telemetry subpackage — allowlisted root scanning for workspace fingerprinting."""
from .evidence import RootEvidence, WorkspaceEvidence, merge_evidence
from .monitor import RootMonitor
from .scanner import TelemetryScanner, scan_roots

__all__ = [
    "RootEvidence",
    "WorkspaceEvidence",
    "merge_evidence",
    "RootMonitor",
    "TelemetryScanner",
    "scan_roots",
]
