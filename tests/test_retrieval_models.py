"""Tests for retrieval pipeline data models."""
import pytest
from src.multimcp.retrieval.models import RetrievalConfig, RetrievalContext, ScoredTool


class TestRetrievalContext:
    def test_minimal_creation(self):
        ctx = RetrievalContext(session_id="test-1")
        assert ctx.session_id == "test-1"
        assert ctx.query == ""
        assert ctx.tool_call_history == []
        assert ctx.server_hint is None

    def test_full_creation(self):
        ctx = RetrievalContext(
            session_id="s1",
            query="search repos",
            tool_call_history=["github__get_me"],
            server_hint="github",
        )
        assert ctx.query == "search repos"
        assert ctx.server_hint == "github"

    def test_tool_call_history_is_mutable(self):
        ctx = RetrievalContext(session_id="s1")
        ctx.tool_call_history.append("tool_a")
        assert "tool_a" in ctx.tool_call_history

    def test_separate_instances_dont_share_lists(self):
        """Each instance must have its own tool_call_history list."""
        ctx1 = RetrievalContext(session_id="s1")
        ctx2 = RetrievalContext(session_id="s2")
        ctx1.tool_call_history.append("only_in_ctx1")
        assert ctx1.tool_call_history != ctx2.tool_call_history


class TestScoredTool:
    def test_holds_reference_not_copy(self):
        """ScoredTool must hold a reference to ToolMapping, not a copy."""
        from unittest.mock import MagicMock
        mapping = MagicMock()
        st = ScoredTool(tool_key="github__get_me", tool_mapping=mapping)
        assert st.tool_mapping is mapping
        assert st.score == 1.0
        assert st.tier == "full"

    def test_summary_tier(self):
        from unittest.mock import MagicMock
        st = ScoredTool(
            tool_key="exa__search",
            tool_mapping=MagicMock(),
            score=0.7,
            tier="summary",
        )
        assert st.tier == "summary"
        assert st.score == 0.7


class TestRetrievalConfig:
    def test_defaults_disabled(self):
        config = RetrievalConfig()
        assert config.enabled is False
        assert config.top_k == 10
        assert config.full_description_count == 3
        assert config.anchor_tools == []

    def test_custom_values(self):
        config = RetrievalConfig(
            enabled=True,
            top_k=5,
            full_description_count=2,
            anchor_tools=["github__get_me"],
        )
        assert config.enabled is True
        assert config.top_k == 5
        assert config.full_description_count == 2
        assert config.anchor_tools == ["github__get_me"]

    def test_separate_instances_dont_share_anchor_lists(self):
        """Each config must have its own anchor_tools list."""
        c1 = RetrievalConfig()
        c2 = RetrievalConfig()
        c1.anchor_tools.append("only_in_c1")
        assert c1.anchor_tools != c2.anchor_tools
