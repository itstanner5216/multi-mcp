"""Tests for TieredAssembler two-tier description compression."""

import json
import pytest
from unittest.mock import MagicMock
from mcp import types
from src.multimcp.retrieval.assembler import TieredAssembler
from src.multimcp.retrieval.models import RetrievalConfig, ScoredTool


def _make_scored(
    name: str, desc: str, score: float, properties: dict = None
) -> ScoredTool:
    if properties is None:
        properties = {
            "query": {"type": "string", "description": "The search query to execute"}
        }
    tool = types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": properties},
    )
    m = MagicMock()
    m.tool = tool
    m.server_name = "test"
    return ScoredTool(tool_key=f"test__{name}", tool_mapping=m, score=score)


class TestTieredAssembler:
    def setup_method(self):
        self.config = RetrievalConfig(
            enabled=True,
            full_description_count=2,
        )
        self.assembler = TieredAssembler()

    def test_full_tier_preserves_description(self):
        tools = [
            _make_scored(
                "search", "Search for repositories by name, topic, or description", 0.9
            ),
            _make_scored("read", "Read the full contents of a specific file", 0.8),
        ]
        result = self.assembler.assemble(tools, self.config)
        assert (
            result[0].description
            == "Search for repositories by name, topic, or description"
        )
        assert result[1].description == "Read the full contents of a specific file"

    def test_summary_tier_truncates_description(self):
        long_desc = "This is a very detailed description that goes on and on about what this tool does, including all the edge cases and special behaviors that you need to know about in order to use it effectively."
        tools = [
            _make_scored("top1", "Short", 0.9),
            _make_scored("top2", "Short", 0.8),
            _make_scored("summary", long_desc, 0.5),
        ]
        result = self.assembler.assemble(tools, self.config)
        # Third tool should be summary tier
        assert len(result[2].description) <= 100
        assert result[2].description.endswith("…")

    def test_summary_tier_strips_property_descriptions(self):
        props = {
            "query": {"type": "string", "description": "The search query to send"},
            "limit": {"type": "integer", "description": "Maximum number of results"},
        }
        tools = [
            _make_scored("top1", "Short", 0.9),
            _make_scored("top2", "Short", 0.8),
            _make_scored("summary", "A tool description", 0.5, properties=props),
        ]
        result = self.assembler.assemble(tools, self.config)
        schema = result[2].inputSchema
        for prop_name, prop_val in schema["properties"].items():
            assert "description" not in prop_val

    def test_full_tier_preserves_property_descriptions(self):
        props = {
            "query": {"type": "string", "description": "The search query"},
        }
        tools = [_make_scored("top", "Short", 0.9, properties=props)]
        result = self.assembler.assemble(tools, self.config)
        assert (
            result[0].inputSchema["properties"]["query"]["description"]
            == "The search query"
        )

    def test_does_not_mutate_originals(self):
        original_desc = "Original full description of the tool"
        tool = _make_scored("tool", original_desc, 0.5)
        original_tool_obj = tool.tool_mapping.tool
        self.assembler.assemble(
            [_make_scored("top1", "S", 0.9), _make_scored("top2", "S", 0.8), tool],
            self.config,
        )
        assert original_tool_obj.description == original_desc

    def test_short_desc_not_truncated(self):
        tools = [
            _make_scored("top1", "S", 0.9),
            _make_scored("top2", "S", 0.8),
            _make_scored("short", "A short description.", 0.5),
        ]
        result = self.assembler.assemble(tools, self.config)
        assert result[2].description == "A short description."

    def test_first_sentence_extraction(self):
        desc = "Search repositories. Also supports filtering by language and stars."
        tools = [
            _make_scored("top1", "S", 0.9),
            _make_scored("top2", "S", 0.8),
            _make_scored("sent", desc, 0.5),
        ]
        result = self.assembler.assemble(tools, self.config)
        # Should truncate to first sentence
        assert "Search repositories." in result[2].description

    def test_token_reduction(self):
        """Summary tier should be measurably smaller than full tier."""
        long_desc = "This is a comprehensive tool for managing complex operations across distributed systems with advanced filtering and sorting capabilities."
        props = {
            f"prop{i}": {
                "type": "string",
                "description": f"Detailed description of property {i} and how it is used",
            }
            for i in range(5)
        }
        tools = [
            _make_scored("top1", "Short", 0.9),
            _make_scored("top2", "Short", 0.8),
            _make_scored("full", long_desc, 0.5, properties=props),
        ]
        result = self.assembler.assemble(tools, self.config)
        # Compare summary version of 'full' tool against its original full-description version
        original_full_size = len(json.dumps(tools[2].tool_mapping.tool.model_dump()))
        summary_size = len(json.dumps(result[2].model_dump()))
        # Summary should be smaller than the original (descriptions stripped + truncated)
        assert summary_size < original_full_size

    def test_empty_list(self):
        result = self.assembler.assemble([], self.config)
        assert result == []

    def test_nested_schema_simplification(self):
        """Deeply nested schemas should also have descriptions stripped."""
        props = {
            "files": {
                "type": "array",
                "description": "Array of file objects",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "content": {"type": "string", "description": "File content"},
                    },
                },
            }
        }
        tools = [
            _make_scored("top1", "S", 0.9),
            _make_scored("top2", "S", 0.8),
            _make_scored("nested", "A tool with nested schema", 0.5, properties=props),
        ]
        result = self.assembler.assemble(tools, self.config)
        schema = result[2].inputSchema
        items = schema["properties"]["files"].get("items", {})
        if "properties" in items:
            for pval in items["properties"].values():
                assert "description" not in pval
