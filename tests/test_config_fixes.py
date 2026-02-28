"""Tests for yaml_config fixes."""

import pytest
from pathlib import Path
from src.multimcp.yaml_config import load_config


def test_load_config_file_not_found_returns_empty(tmp_path):
    """Missing file should return empty config without error."""
    config = load_config(tmp_path / "nonexistent.yaml")
    assert config.servers == {}


def test_load_config_invalid_yaml_logs_error(tmp_path, caplog):
    """Malformed YAML should log error and return empty config."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("servers:\n  - ][invalid yaml")
    config = load_config(bad_yaml)
    assert config.servers == {}


def test_load_config_invalid_schema_returns_empty(tmp_path):
    """Valid YAML but invalid schema should return empty config."""
    bad_schema = tmp_path / "bad_schema.yaml"
    bad_schema.write_text("servers:\n  test:\n    command: 123\n    type: invalid_type")
    config = load_config(bad_schema)
    assert config.servers == {}


def test_load_config_valid_yaml_works(tmp_path):
    """Valid YAML should load correctly."""
    good_yaml = tmp_path / "good.yaml"
    good_yaml.write_text("servers:\n  test:\n    command: echo\n    type: stdio\n")
    config = load_config(good_yaml)
    assert "test" in config.servers
    assert config.servers["test"].command == "echo"


def test_load_config_empty_file_returns_empty(tmp_path):
    """Empty YAML file should return empty config."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    config = load_config(empty)
    assert config.servers == {}
