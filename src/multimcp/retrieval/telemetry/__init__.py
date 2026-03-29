"""Telemetry subpackage — allowlisted root scanning for workspace fingerprinting."""
from .evidence import RootEvidence, WorkspaceEvidence, merge_evidence

# Scanner is added in Task 2; import deferred to avoid circular issues during build
try:
    from .scanner import TelemetryScanner, scan_roots
except ImportError:  # pragma: no cover
    TelemetryScanner = None  # type: ignore[assignment,misc]
    scan_roots = None  # type: ignore[assignment]

__all__ = [
    "RootEvidence",
    "WorkspaceEvidence",
    "merge_evidence",
    "TelemetryScanner",
    "scan_roots",
]
