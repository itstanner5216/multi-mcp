"""Tests for ToolCatalogSnapshot — versioning and schema_hash stability."""
import time
import pytest
from unittest.mock import MagicMock
from mcp import types

from src.multimcp.retrieval.catalog import build_snapshot, _version_counter
from src.multimcp.retrieval.models import ToolCatalogSnapshot, ToolDoc


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tool(name: str, desc: str = "", params: list[str] | None = None) -> types.Tool:
    props = {p: {"type": "string"} for p in (params or [])}
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": props},
    )


def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    return m


def _simple_registry():
    return {
        "github__search_repositories": _make_mapping(
            "github", _make_tool("search_repositories", "Search GitHub repos", ["query"])
        ),
        "fs__read_file": _make_mapping(
            "fs", _make_tool("read_file", "Read a file", ["path"])
        ),
    }


# ── Snapshot creation tests ───────────────────────────────────────────────────

class TestSnapshotCreation:
    def test_returns_tool_catalog_snapshot(self):
        snapshot = build_snapshot(_simple_registry())
        assert isinstance(snapshot, ToolCatalogSnapshot)

    def test_doc_count_matches_registry(self):
        registry = _simple_registry()
        snapshot = build_snapshot(registry)
        assert len(snapshot.docs) == len(registry)

    def test_all_keys_present(self):
        registry = _simple_registry()
        snapshot = build_snapshot(registry)
        keys = {doc.tool_key for doc in snapshot.docs}
        assert keys == set(registry.keys())

    def test_tool_name_extracted(self):
        snapshot = build_snapshot({
            "github__create_issue": _make_mapping(
                "github", _make_tool("create_issue", "Create a GitHub issue", ["title"])
            )
        })
        doc = snapshot.docs[0]
        assert doc.tool_name == "create_issue"

    def test_namespace_extracted(self):
        snapshot = build_snapshot({
            "github__create_issue": _make_mapping(
                "github", _make_tool("create_issue", "Create a GitHub issue", ["title"])
            )
        })
        doc = snapshot.docs[0]
        assert doc.namespace == "github"

    def test_description_preserved(self):
        snapshot = build_snapshot({
            "svc__tool": _make_mapping("svc", _make_tool("tool", "My description", []))
        })
        assert snapshot.docs[0].description == "My description"

    def test_parameter_names_space_joined(self):
        snapshot = build_snapshot({
            "svc__tool": _make_mapping(
                "svc", _make_tool("tool", "", ["alpha", "beta", "gamma"])
            )
        })
        param_str = snapshot.docs[0].parameter_names
        assert "alpha" in param_str
        assert "beta" in param_str
        assert "gamma" in param_str

    def test_retrieval_aliases_empty(self):
        """catalog.py leaves retrieval_aliases empty — populated by BMXFRetriever."""
        snapshot = build_snapshot(_simple_registry())
        for doc in snapshot.docs:
            assert doc.retrieval_aliases == ""

    def test_built_at_is_recent(self):
        before = time.time()
        snapshot = build_snapshot(_simple_registry())
        after = time.time()
        assert before <= snapshot.built_at <= after

    def test_tool_without_namespace(self):
        """Tools without __ separator should have empty namespace."""
        no_ns_mapping = _make_mapping("", _make_tool("standalone_tool", "No namespace"))
        snapshot = build_snapshot({"standalone_tool": no_ns_mapping})
        doc = snapshot.docs[0]
        assert doc.namespace == ""
        assert doc.tool_name == "standalone_tool"

    def test_none_description_becomes_empty_string(self):
        mapping = _make_mapping("svc", _make_tool("tool", None))
        mapping.tool.description = None
        snapshot = build_snapshot({"svc__tool": mapping})
        assert snapshot.docs[0].description == ""

    def test_none_input_schema_safe(self):
        mapping = _make_mapping("svc", _make_tool("tool", "desc"))
        mapping.tool.inputSchema = None
        snapshot = build_snapshot({"svc__tool": mapping})
        assert snapshot.docs[0].parameter_names == ""


# ── schema_hash stability tests ───────────────────────────────────────────────

class TestSchemaHash:
    def test_identical_registries_produce_same_hash(self):
        r1 = _simple_registry()
        r2 = _simple_registry()
        s1 = build_snapshot(r1)
        s2 = build_snapshot(r2)
        assert s1.schema_hash == s2.schema_hash

    def test_insertion_order_does_not_affect_hash(self):
        """Hash must be stable regardless of dict insertion order."""
        r1 = {
            "a__tool1": _make_mapping("a", _make_tool("tool1", "desc1")),
            "b__tool2": _make_mapping("b", _make_tool("tool2", "desc2")),
        }
        r2 = {
            "b__tool2": _make_mapping("b", _make_tool("tool2", "desc2")),
            "a__tool1": _make_mapping("a", _make_tool("tool1", "desc1")),
        }
        s1 = build_snapshot(r1)
        s2 = build_snapshot(r2)
        assert s1.schema_hash == s2.schema_hash

    def test_hash_changes_on_description_update(self):
        registry = _simple_registry()
        s1 = build_snapshot(registry)

        # Change one tool's description
        registry["fs__read_file"].tool.description = "CHANGED description"
        s2 = build_snapshot(registry)

        assert s1.schema_hash != s2.schema_hash

    def test_hash_changes_on_parameter_addition(self):
        registry = _simple_registry()
        s1 = build_snapshot(registry)

        # Add a parameter to one tool
        registry["github__search_repositories"].tool.inputSchema = {
            "type": "object",
            "properties": {"query": {"type": "string"}, "new_param": {"type": "string"}},
        }
        s2 = build_snapshot(registry)

        assert s1.schema_hash != s2.schema_hash

    def test_hash_changes_on_tool_addition(self):
        registry = _simple_registry()
        s1 = build_snapshot(registry)

        registry["new__tool"] = _make_mapping("new", _make_tool("tool", "A brand new tool"))
        s2 = build_snapshot(registry)

        assert s1.schema_hash != s2.schema_hash

    def test_hash_changes_on_tool_removal(self):
        registry = _simple_registry()
        s1 = build_snapshot(registry)

        del registry["fs__read_file"]
        s2 = build_snapshot(registry)

        assert s1.schema_hash != s2.schema_hash

    def test_hash_is_sha256_hex(self):
        """Hash should be a 64-char hex string (SHA-256)."""
        snapshot = build_snapshot(_simple_registry())
        assert len(snapshot.schema_hash) == 64
        int(snapshot.schema_hash, 16)  # Must be valid hex


# ── Versioning tests ──────────────────────────────────────────────────────────

class TestVersioning:
    def test_version_increments_each_call(self):
        r = _simple_registry()
        s1 = build_snapshot(r)
        s2 = build_snapshot(r)
        s3 = build_snapshot(r)

        assert int(s2.version) == int(s1.version) + 1
        assert int(s3.version) == int(s2.version) + 1

    def test_version_is_string(self):
        snapshot = build_snapshot(_simple_registry())
        assert isinstance(snapshot.version, str)
        assert snapshot.version.isdigit()

    def test_empty_registry_produces_valid_snapshot(self):
        snapshot = build_snapshot({})
        assert isinstance(snapshot, ToolCatalogSnapshot)
        assert snapshot.docs == []
        assert len(snapshot.schema_hash) == 64
