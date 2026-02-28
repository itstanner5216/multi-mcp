"""Tests for SessionStateManager with monotonic guarantees."""
import pytest
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import RetrievalConfig


class TestSessionStateManager:
    def setup_method(self):
        self.config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
        )
        self.mgr = SessionStateManager(self.config)

    def test_new_session_has_anchors(self):
        tools = self.mgr.get_or_create_session("s1")
        assert "github__get_me" in tools

    def test_get_active_tools_returns_anchors(self):
        self.mgr.get_or_create_session("s1")
        active = self.mgr.get_active_tools("s1")
        assert "github__get_me" in active

    def test_add_tools_returns_newly_added(self):
        self.mgr.get_or_create_session("s1")
        newly_added = self.mgr.add_tools("s1", ["exa__search", "obsidian__read"])
        assert "exa__search" in newly_added
        assert "obsidian__read" in newly_added

    def test_add_duplicate_returns_empty(self):
        self.mgr.get_or_create_session("s1")
        self.mgr.add_tools("s1", ["exa__search"])
        # Add same tool again
        newly_added = self.mgr.add_tools("s1", ["exa__search"])
        assert newly_added == []

    def test_add_anchor_is_not_new(self):
        self.mgr.get_or_create_session("s1")
        newly_added = self.mgr.add_tools("s1", ["github__get_me"])
        assert newly_added == []

    def test_monotonic_guarantee(self):
        """Active tool set must never shrink."""
        self.mgr.get_or_create_session("s1")
        self.mgr.add_tools("s1", ["tool_a", "tool_b"])
        count_1 = len(self.mgr.get_active_tools("s1"))
        self.mgr.add_tools("s1", ["tool_c"])
        count_2 = len(self.mgr.get_active_tools("s1"))
        assert count_2 >= count_1

    def test_monotonic_no_removal_api(self):
        """There must be no way to remove individual tools from a session."""
        self.mgr.get_or_create_session("s1")
        self.mgr.add_tools("s1", ["tool_a"])
        # Only cleanup_session can remove tools, and it removes the entire session
        assert not hasattr(self.mgr, "remove_tools")
        assert not hasattr(self.mgr, "remove_tool")

    def test_cleanup_removes_session(self):
        self.mgr.get_or_create_session("s1")
        self.mgr.add_tools("s1", ["tool_a"])
        self.mgr.cleanup_session("s1")
        # New session should only have anchors
        tools = self.mgr.get_or_create_session("s1")
        assert "tool_a" not in tools

    def test_cleanup_nonexistent_session_is_safe(self):
        self.mgr.cleanup_session("nonexistent")  # Should not raise

    def test_unknown_session_get_active_returns_empty(self):
        active = self.mgr.get_active_tools("unknown")
        assert active == set()

    def test_unknown_session_add_tools_returns_empty(self):
        newly_added = self.mgr.add_tools("unknown", ["tool_a"])
        assert newly_added == []

    def test_multiple_sessions_isolated(self):
        self.mgr.get_or_create_session("s1")
        self.mgr.get_or_create_session("s2")
        self.mgr.add_tools("s1", ["tool_a"])
        assert "tool_a" in self.mgr.get_active_tools("s1")
        assert "tool_a" not in self.mgr.get_active_tools("s2")

    def test_get_or_create_returns_copy(self):
        """Callers must not be able to mutate internal state via returned set."""
        self.mgr.get_or_create_session("s1")
        returned = self.mgr.get_or_create_session("s1")
        returned.add("injected_tool")
        actual = self.mgr.get_active_tools("s1")
        assert "injected_tool" not in actual

    def test_get_active_tools_returns_copy(self):
        """Callers must not be able to mutate internal state via returned set."""
        self.mgr.get_or_create_session("s1")
        returned = self.mgr.get_active_tools("s1")
        returned.add("injected_tool")
        actual = self.mgr.get_active_tools("s1")
        assert "injected_tool" not in actual

    def test_no_anchors_config(self):
        """Session with no anchor tools starts empty."""
        config = RetrievalConfig(enabled=True, anchor_tools=[])
        mgr = SessionStateManager(config)
        tools = mgr.get_or_create_session("s1")
        assert tools == set()

    def test_multiple_anchors(self):
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me", "exa__search", "obsidian__read"],
        )
        mgr = SessionStateManager(config)
        tools = mgr.get_or_create_session("s1")
        assert tools == {"github__get_me", "exa__search", "obsidian__read"}
