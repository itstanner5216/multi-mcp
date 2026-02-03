"""
Configuration for audit logging.
"""

from typing import Optional


class AuditConfig:
    """Configuration for audit logging."""

    def __init__(
        self,
        log_dir: str = "./logs",
        rotation: str = "10 MB",
        retention: str = "30 days",
        compression: str = "gz",
    ):
        self.log_dir = log_dir
        self.rotation = rotation
        self.retention = retention
        self.compression = compression


# Default configuration instance
DEFAULT_AUDIT_CONFIG = AuditConfig()
