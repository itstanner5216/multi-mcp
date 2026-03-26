"""Shared TOML read/write helpers for adapters.

Uses ``tomllib`` (stdlib, Python ≥ 3.11) or ``tomli`` (backport) for reading.
Uses ``tomli_w`` for writing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def read_toml(path: Path) -> dict:
    """Read and parse a TOML file.  Returns empty dict if file doesn't exist."""
    if not path.exists():
        return {}
    try:
        import tomllib  # type: ignore[import]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import,no-redef]
        except ImportError as exc:
            raise ImportError(
                "TOML reading requires Python 3.11+ (stdlib tomllib) or 'tomli' package. "
                "Install with: pip install tomli"
            ) from exc
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def write_toml(path: Path, data: dict) -> None:
    """Write *data* to *path* in TOML format."""
    try:
        import tomli_w  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "TOML writing requires the 'tomli_w' package. "
            "Install with: pip install tomli_w"
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        tomli_w.dump(data, fh)
