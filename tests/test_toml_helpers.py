"""Tests for src/multimcp/adapters/_toml_helpers.py.

Covers: read_toml (nonexistent file, valid TOML, ImportError fallbacks) and
write_toml (creates file, creates parent directories, roundtrip fidelity).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.multimcp.adapters._toml_helpers import read_toml, write_toml


# ---------------------------------------------------------------------------
# read_toml
# ---------------------------------------------------------------------------

class TestReadToml:
    def test_returns_empty_dict_for_nonexistent_file(self, tmp_path: Path) -> None:
        result = read_toml(tmp_path / "no_such_file.toml")
        assert result == {}

    def test_reads_simple_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "config.toml"
        p.write_bytes(b'[section]\nkey = "value"\nnumber = 42\n')
        result = read_toml(p)
        assert result == {"section": {"key": "value", "number": 42}}

    def test_reads_nested_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "nested.toml"
        p.write_bytes(
            b'[mcp_servers.my-server]\n'
            b'command = "python"\n'
            b'args = ["s.py"]\n'
        )
        result = read_toml(p)
        assert result["mcp_servers"]["my-server"]["command"] == "python"
        assert result["mcp_servers"]["my-server"]["args"] == ["s.py"]

    def test_reads_array_of_tables(self, tmp_path: Path) -> None:
        p = tmp_path / "array.toml"
        p.write_bytes(
            b'[[mcp.servers]]\nname = "srv1"\nurl = "http://localhost:8080/sse"\n'
            b'[[mcp.servers]]\nname = "srv2"\ncommand = "node"\n'
        )
        result = read_toml(p)
        assert len(result["mcp"]["servers"]) == 2
        assert result["mcp"]["servers"][0]["name"] == "srv1"
        assert result["mcp"]["servers"][1]["name"] == "srv2"

    def test_reads_empty_toml_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.toml"
        p.write_bytes(b"")
        result = read_toml(p)
        assert result == {}

    def test_raises_import_error_when_no_toml_library(self, tmp_path: Path) -> None:
        """If neither tomllib nor tomli is available, ImportError should be raised."""
        p = tmp_path / "config.toml"
        p.write_bytes(b'key = "value"\n')

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="TOML reading requires"):
                read_toml(p)


# ---------------------------------------------------------------------------
# write_toml
# ---------------------------------------------------------------------------

class TestWriteToml:
    def test_creates_file_with_toml_content(self, tmp_path: Path) -> None:
        p = tmp_path / "output.toml"
        data = {"section": {"key": "value", "number": 42}}
        write_toml(p, data)
        assert p.exists()
        result = read_toml(p)
        assert result == data

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "config.toml"
        write_toml(p, {"key": "val"})
        assert p.exists()

    def test_roundtrip_preserves_data(self, tmp_path: Path) -> None:
        p = tmp_path / "rt.toml"
        original = {
            "mcp_servers": {
                "alpha": {"command": "python", "args": ["a.py"]},
                "beta": {"command": "node", "args": ["b.js"]},
            }
        }
        write_toml(p, original)
        result = read_toml(p)
        assert result == original

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "config.toml"
        write_toml(p, {"old": "data"})
        write_toml(p, {"new": "data"})
        result = read_toml(p)
        assert result == {"new": "data"}
        assert "old" not in result

    def test_raises_import_error_when_tomli_w_missing(self, tmp_path: Path) -> None:
        """If tomli_w is not available, ImportError should be raised."""
        p = tmp_path / "config.toml"
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "tomli_w":
                raise ImportError("No module named 'tomli_w'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="TOML writing requires"):
                write_toml(p, {"key": "value"})

    def test_write_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.toml"
        write_toml(p, {})
        result = read_toml(p)
        assert result == {}

    def test_write_boolean_and_list_values(self, tmp_path: Path) -> None:
        p = tmp_path / "types.toml"
        data = {"flags": {"enabled": True, "items": [1, 2, 3]}}
        write_toml(p, data)
        result = read_toml(p)
        assert result["flags"]["enabled"] is True
        assert result["flags"]["items"] == [1, 2, 3]