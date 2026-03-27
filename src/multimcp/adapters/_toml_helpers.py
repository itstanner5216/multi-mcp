"""TOML read/write helpers for MCP adapters.

Uses ``tomllib`` (stdlib ≥ 3.11) or ``tomli`` for reading and ``tomli_w``
for writing.  Both imports are done lazily so that the module can be imported
even when the optional libraries are not installed – errors are raised only
when the helpers are actually called.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict


def read_toml(path: Path) -> Dict:
    """Read a TOML file and return its contents as a dict.

    Returns an empty dict when *path* does not exist.
    Raises ``ImportError`` when no TOML reading library is available.
    """
    if not path.exists():
        return {}

    tomllib_mod = None
    try:
        import tomllib
        tomllib_mod = tomllib
    except ImportError:
        try:
            import tomli  # type: ignore[import-not-found]
            tomllib_mod = tomli
        except ImportError:
            pass

    if tomllib_mod is None:
        raise ImportError(
            "TOML reading requires 'tomllib' (Python 3.11+) or 'tomli' (`pip install tomli`)"
        )
    with open(path, "rb") as fh:
        return tomllib_mod.load(fh)


def write_toml(path: Path, data: Dict) -> None:
    """Write *data* to *path* in TOML format, creating parent directories.

    Raises ``ImportError`` when ``tomli_w`` is not installed.
    """
    try:
        import tomli_w
    except ImportError:
        raise ImportError("TOML writing requires 'tomli_w' (`pip install tomli_w`)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(data).encode("utf-8"))
