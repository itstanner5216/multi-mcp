"""
Audit logging for MCP tool invocations.

Logs all tool calls and failures to JSONL format with rotation support.
"""

from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime, timezone
import json
import re

from loguru import logger

from .config import AuditConfig, DEFAULT_AUDIT_CONFIG

_SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|token|password|passwd|secret|credential|auth|bearer)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"


def _sanitize_arguments(args):
    """Recursively redact sensitive values from arguments dict."""
    if args is None:
        return None
    if not isinstance(args, dict):
        return args
    sanitized = {}
    for key, value in args.items():
        if _SENSITIVE_KEYS.search(key):
            sanitized[key] = _REDACTED
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_arguments(value)
        else:
            sanitized[key] = value
    return sanitized


class AuditLogger:
    """
    Audit logger for MCP tool invocations.

    Logs tool calls and failures to a JSONL file with automatic rotation.
    """

    def __init__(
        self,
        log_dir: Optional[str] = None,
        rotation: Optional[str] = None,
        retention: Optional[str] = None,
        compression: Optional[str] = None,
        config: Optional[AuditConfig] = None,
    ):
        """
        Initialize audit logger.

        Args:
            log_dir: Directory for audit logs (default: ./logs)
            rotation: Log rotation size/time (default: 10 MB)
            retention: How long to keep logs (default: 30 days)
            compression: Compression format (default: gz)
            config: AuditConfig instance (overrides other params)
        """
        if config:
            self.config = config
        else:
            self.config = AuditConfig(
                log_dir=log_dir or DEFAULT_AUDIT_CONFIG.log_dir,
                rotation=rotation or DEFAULT_AUDIT_CONFIG.rotation,
                retention=retention or DEFAULT_AUDIT_CONFIG.retention,
                compression=compression or DEFAULT_AUDIT_CONFIG.compression,
            )

        # Ensure log directory exists
        self.log_path = Path(self.config.log_dir)
        self.log_path.mkdir(parents=True, exist_ok=True)

        # Configure loguru for audit logging
        self.log_file = self.log_path / "audit.jsonl"

        # Add a sink for audit logs with rotation
        self._sink_id = logger.add(
            str(self.log_file),
            format="{message}",  # Raw JSON, no formatting
            rotation=self.config.rotation,
            retention=self.config.retention,
            compression=self.config.compression,
            serialize=False,  # We'll serialize manually
            enqueue=True,  # Thread-safe
            filter=lambda record: record["extra"].get("audit") is True,
        )

    def log_tool_call(
        self,
        tool_name: str,
        server_name: str,
        arguments: Dict[str, Any],
        result: Optional[Any] = None,
    ) -> None:
        """
        Log a successful tool invocation.

        Args:
            tool_name: Name of the tool called
            server_name: Name of the server handling the call
            arguments: Arguments passed to the tool
            result: Result returned (optional)
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "tool_call",
            "tool_name": tool_name,
            "server_name": server_name,
            "arguments": _sanitize_arguments(arguments),
            "status": "success",
        }

        if result is not None:
            entry["result"] = result

        # Write JSONL entry
        self._write_entry(entry)

    def log_tool_failure(
        self, tool_name: str, server_name: str, arguments: Dict[str, Any], error: str
    ) -> None:
        """
        Log a failed tool invocation.

        Args:
            tool_name: Name of the tool called
            server_name: Name of the server that failed
            arguments: Arguments passed to the tool
            error: Error message or exception details
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "tool_call",
            "tool_name": tool_name,
            "server_name": server_name,
            "arguments": _sanitize_arguments(arguments),
            "status": "error",
            "error": error,
        }

        # Write JSONL entry
        self._write_entry(entry)

    def _write_entry(self, entry: Dict[str, Any]) -> None:
        """Write a JSONL entry to the audit log."""
        json_line = json.dumps(entry, separators=(",", ":"), default=str)
        logger.bind(audit=True).info(json_line)

    def close(self) -> None:
        """Remove the audit log sink from loguru."""
        logger.remove(self._sink_id)
