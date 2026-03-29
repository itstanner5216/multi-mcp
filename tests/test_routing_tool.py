"""Tests for routing tool -- ROUTER-01 through ROUTER-04 and TEST-04."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock

import pytest
from mcp import types

from src.multimcp.retrieval.routing_tool import (
    ROUTING_TOOL_KEY,
    ROUTING_TOOL_NAME,
    build_routing_tool_schema,
    format_namespace_grouped,
    handle_routing_call,
)
from src.multimcp.retrieval.assembler import TieredAssembler
from src.multimcp.retrieval.models import RetrievalConfig, ScoredTool


# -- Helpers ------------------------------------------------------------------

def _make_tool_mapping(server: str, tool_name: str, description: str = "A tool") -> MagicMock:
    mapping = MagicMock()
    mapping.server_name = server
    mapping.tool = types.Tool(
        name=f"{server}__{tool_name}",
        description=description,
        inputSchema={"type": "object", "properties": {"arg": {"type": "string"}}},
    )
    return mapping


def _make_scored(server: str, tool: str, score: float = 1.0) -> ScoredTool:
    return ScoredTool(
        tool_key=f"{server}__{tool}",
        tool_mapping=_make_tool_mapping(server, tool),
        score=score,
    )


# -- ROUTING_TOOL_NAME / ROUTING_TOOL_KEY -------------------------------------

def test_tool_name_constant():
    assert ROUTING_TOOL_NAME == "request_tool"


def test_tool_key_constant():
    assert ROUTING_TOOL_KEY == "__routing__request_tool"


# -- build_routing_tool_schema (ROUTER-02) ------------------------------------

def test_schema_name():
    t = build_routing_tool_schema(["a__x"])
    assert t.name == "request_tool"


def test_schema_enum_single():
    t = build_routing_tool_schema(["github__search"])
    assert t.inputSchema["properties"]["name"]["enum"] == ["github__search"]


def test_schema_enum_multiple():
    ids = ["github__search", "brave-search__web", "npm__install"]
    t = build_routing_tool_schema(ids)
    assert t.inputSchema["properties"]["name"]["enum"] == ids


def test_schema_empty_enum():
    t = build_routing_tool_schema([])
    assert t.inputSchema["properties"]["name"]["enum"] == []


def test_schema_required():
    t = build_routing_tool_schema(["a__b"])
    assert t.inputSchema["required"] == ["name"]


def test_schema_has_describe_property():
    t = build_routing_tool_schema(["a__b"])
    assert "describe" in t.inputSchema["properties"]
    assert t.inputSchema["properties"]["describe"]["type"] == "boolean"


def test_schema_has_arguments_property():
    t = build_routing_tool_schema(["a__b"])
    assert "arguments" in t.inputSchema["properties"]
    assert t.inputSchema["properties"]["arguments"]["type"] == "object"


def test_router04_large_enum():
    """ROUTER-04: routing tool can hold all tools beyond top-K."""
    ids = [f"server{i}__tool{j}" for i in range(5) for j in range(5)]  # 25 tools
    t = build_routing_tool_schema(ids)
    assert len(t.inputSchema["properties"]["name"]["enum"]) == 25


# -- format_namespace_grouped (ROUTER-03) -------------------------------------

def test_env_namespace_first():
    result = format_namespace_grouped(
        ["npm__b", "github__a", "github__c"],
        env_namespaces=["github"],
    )
    assert result == ["github__a", "github__c", "npm__b"]


def test_no_env_namespace_alphabetical():
    result = format_namespace_grouped(["z__tool", "a__tool", "m__tool"], env_namespaces=[])
    assert result == ["a__tool", "m__tool", "z__tool"]


def test_multiple_env_namespaces():
    result = format_namespace_grouped(
        ["npm__x", "github__a", "cargo__y"],
        env_namespaces=["cargo", "github"],
    )
    assert result[0].startswith("cargo__")
    assert result[1].startswith("github__")
    assert result[2].startswith("npm__")


def test_env_namespace_not_present_skipped():
    result = format_namespace_grouped(["npm__x"], env_namespaces=["github"])
    assert result == ["npm__x"]


def test_tools_without_namespace_separator():
    result = format_namespace_grouped(["bare_tool"], env_namespaces=[])
    assert result == ["bare_tool"]


# -- handle_routing_call ------------------------------------------------------

def test_describe_true_returns_schema_json():
    mapping = _make_tool_mapping("github", "search_repos", "Search GitHub")
    registry = {"github__search_repos": mapping}
    content = handle_routing_call(
        name="github__search_repos",
        describe=True,
        arguments={},
        tool_to_server=registry,
    )
    assert len(content) == 1
    assert content[0].type == "text"
    data = json.loads(content[0].text)
    assert "inputSchema" in data
    assert data["description"] == "Search GitHub"


def test_describe_true_missing_tool():
    content = handle_routing_call(
        name="nonexistent__tool",
        describe=True,
        arguments={},
        tool_to_server={},
    )
    assert len(content) == 1
    assert "Tool not found" in content[0].text or "not found" in content[0].text.lower()


def test_describe_false_returns_proxy_sentinel():
    mapping = _make_tool_mapping("github", "create_issue")
    registry = {"github__create_issue": mapping}
    content = handle_routing_call(
        name="github__create_issue",
        describe=False,
        arguments={"title": "bug"},
        tool_to_server=registry,
    )
    assert len(content) == 1
    assert "__PROXY_CALL__:github__create_issue" in content[0].text


# -- TieredAssembler routing_tool_schema integration --------------------------

def test_assembler_without_routing_tool():
    """Existing behavior: no routing tool schema = no routing tool in result."""
    assembler = TieredAssembler()
    config = RetrievalConfig(full_description_count=2)
    tools = [_make_scored("github", "search"), _make_scored("npm", "install")]
    result = assembler.assemble(tools, config)
    assert len(result) == 2
    assert all(t.name != "request_tool" for t in result)


def test_assembler_with_routing_tool_appended():
    """routing_tool_schema is appended as last tool when provided."""
    assembler = TieredAssembler()
    config = RetrievalConfig(full_description_count=2)
    scored = [_make_scored("github", "search")]
    routing_schema = build_routing_tool_schema(["npm__install", "cargo__build"])
    result = assembler.assemble(scored, config, routing_tool_schema=routing_schema)
    assert result[-1].name == "request_tool"
    assert len(result) == 2  # 1 scored tool + routing tool


def test_assembler_empty_tools_with_routing():
    """Even with no scored tools, routing tool is returned if provided."""
    assembler = TieredAssembler()
    config = RetrievalConfig(full_description_count=2)
    routing_schema = build_routing_tool_schema(["npm__install"])
    result = assembler.assemble([], config, routing_tool_schema=routing_schema)
    assert len(result) == 1
    assert result[0].name == "request_tool"


def test_assembler_backward_compat_none_schema():
    """routing_tool_schema=None (default) does not change existing behavior."""
    assembler = TieredAssembler()
    config = RetrievalConfig(full_description_count=2)
    tools = [_make_scored("github", "search")]
    result_without = assembler.assemble(tools, config)
    result_with_none = assembler.assemble(tools, config, routing_tool_schema=None)
    assert len(result_without) == len(result_with_none)
    assert result_without[0].name == result_with_none[0].name
