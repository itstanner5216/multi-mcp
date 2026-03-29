"""Tests for SessionStateManager promote/demote hysteresis (TEST-05).

Requirements: SESSION-01, SESSION-02, SESSION-03, SESSION-04
"""

from __future__ import annotations

import pytest

from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.session import SessionStateManager


@pytest.fixture()
def config() -> RetrievalConfig:
    return RetrievalConfig()


@pytest.fixture()
def manager(config: RetrievalConfig) -> SessionStateManager:
    return SessionStateManager(config)


class TestPromote:
    def test_promote_adds_new_tools(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        added = manager.promote("s1", ["tool_a", "tool_b"])
        assert set(added) == {"tool_a", "tool_b"}
        active = manager.get_active_tools("s1")
        assert "tool_a" in active and "tool_b" in active

    def test_promote_returns_only_new_keys(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        manager.promote("s1", ["tool_a"])
        # Promote again — tool_a already present, tool_b is new
        added = manager.promote("s1", ["tool_a", "tool_b"])
        assert added == ["tool_b"]

    def test_promote_unknown_session_returns_empty(self, manager: SessionStateManager) -> None:
        result = manager.promote("nonexistent", ["tool_a"])
        assert result == []

    def test_promote_empty_list_is_noop(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        result = manager.promote("s1", [])
        assert result == []

    def test_promote_does_not_affect_other_sessions(
        self, manager: SessionStateManager
    ) -> None:
        manager.get_or_create_session("s1")
        manager.get_or_create_session("s2")
        manager.promote("s1", ["shared_tool"])
        s2_active = manager.get_active_tools("s2")
        assert "shared_tool" not in s2_active


class TestDemote:
    def test_demote_removes_tools(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        manager.promote("s1", ["tool_a", "tool_b", "tool_c"])
        demoted = manager.demote("s1", ["tool_b"], used_this_turn=set())
        assert demoted == ["tool_b"]
        active = manager.get_active_tools("s1")
        assert "tool_b" not in active
        assert "tool_a" in active

    def test_demote_never_removes_used_this_turn(
        self, manager: SessionStateManager
    ) -> None:
        manager.get_or_create_session("s1")
        manager.promote("s1", ["tool_a", "tool_b"])
        # tool_a was used this turn — must not be demoted
        demoted = manager.demote("s1", ["tool_a", "tool_b"], used_this_turn={"tool_a"})
        assert "tool_a" not in demoted
        assert manager.get_active_tools("s1") >= {"tool_a"}  # tool_a still active

    def test_demote_respects_max_per_turn(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        manager.promote("s1", ["a", "b", "c", "d", "e"])
        # Try to demote 5 tools, max_per_turn=3
        demoted = manager.demote("s1", ["a", "b", "c", "d", "e"], used_this_turn=set(), max_per_turn=3)
        assert len(demoted) <= 3

    def test_demote_unknown_session_returns_empty(
        self, manager: SessionStateManager
    ) -> None:
        result = manager.demote("ghost", ["tool_a"], used_this_turn=set())
        assert result == []

    def test_demote_nonexistent_tool_ignored(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        manager.promote("s1", ["tool_a"])
        # tool_x not in active set — should be ignored
        demoted = manager.demote("s1", ["tool_x"], used_this_turn=set())
        assert demoted == []

    def test_demote_empty_list_is_noop(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        manager.promote("s1", ["tool_a"])
        demoted = manager.demote("s1", [], used_this_turn=set())
        assert demoted == []


class TestSessionIsolation:
    """SESSION-04: SessionRoutingState (and active sets) never shared across sessions."""

    def test_promote_in_s1_does_not_affect_s2(
        self, manager: SessionStateManager
    ) -> None:
        manager.get_or_create_session("s1")
        manager.get_or_create_session("s2")
        manager.promote("s1", ["exclusive_tool"])
        assert "exclusive_tool" not in manager.get_active_tools("s2")

    def test_demote_in_s1_does_not_affect_s2(
        self, manager: SessionStateManager
    ) -> None:
        manager.get_or_create_session("s1")
        manager.get_or_create_session("s2")
        manager.promote("s1", ["shared"])
        manager.promote("s2", ["shared"])
        manager.demote("s1", ["shared"], used_this_turn=set())
        # s2 should still have "shared"
        assert "shared" in manager.get_active_tools("s2")

    def test_cleanup_s1_does_not_affect_s2(
        self, manager: SessionStateManager
    ) -> None:
        manager.get_or_create_session("s1")
        manager.get_or_create_session("s2")
        manager.promote("s2", ["tool_x"])
        manager.cleanup_session("s1")
        assert "tool_x" in manager.get_active_tools("s2")

    def test_independent_active_sets(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        manager.get_or_create_session("s2")
        manager.promote("s1", ["a", "b"])
        manager.promote("s2", ["c", "d"])
        s1 = manager.get_active_tools("s1")
        s2 = manager.get_active_tools("s2")
        assert "c" not in s1 and "d" not in s1
        assert "a" not in s2 and "b" not in s2


class TestAddToolsBackwardCompat:
    """Verify add_tools() still works (used by existing code)."""

    def test_add_tools_still_works(self, manager: SessionStateManager) -> None:
        manager.get_or_create_session("s1")
        added = manager.add_tools("s1", ["legacy_tool"])
        assert added == ["legacy_tool"]
        assert "legacy_tool" in manager.get_active_tools("s1")
