"""Tests for FileRetrievalLogger and log_ranking_event additions.

OBS-01: FileRetrievalLogger writes one JSONL line per call to log_ranking_event()
OBS-02: NullLogger.log_ranking_event(event) completes without error and writes nothing
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from src.multimcp.retrieval.models import RankingEvent
from src.multimcp.retrieval.logging import FileRetrievalLogger, NullLogger, RetrievalLogger


def make_event(**overrides) -> RankingEvent:
    defaults = dict(
        session_id="sess-abc",
        turn_number=1,
        catalog_version="v1",
        active_k=5,
        fallback_tier=1,
        router_enum_size=15,
        scorer_latency_ms=42.0,
    )
    defaults.update(overrides)
    return RankingEvent(**defaults)


class TestRetrievalLoggerABC:
    """RetrievalLogger ABC is abstract on log_ranking_event."""

    def test_log_ranking_event_is_abstract(self):
        """log_ranking_event must be abstract in RetrievalLogger."""
        import inspect
        abstract_methods = getattr(RetrievalLogger, "__abstractmethods__", frozenset())
        assert "log_ranking_event" in abstract_methods, (
            "log_ranking_event should be an abstract method on RetrievalLogger"
        )


class TestNullLoggerRankingEvent:
    """NullLogger.log_ranking_event(event) no-ops without error."""

    @pytest.mark.asyncio
    async def test_null_logger_log_ranking_event_no_error(self):
        """NullLogger.log_ranking_event completes without raising."""
        logger = NullLogger()
        event = make_event()
        # Should not raise
        await logger.log_ranking_event(event)

    @pytest.mark.asyncio
    async def test_null_logger_log_ranking_event_writes_nothing(self, tmp_path):
        """NullLogger does not write to any file."""
        logger = NullLogger()
        event = make_event()
        before_files = set(os.listdir(tmp_path))
        await logger.log_ranking_event(event)
        after_files = set(os.listdir(tmp_path))
        assert before_files == after_files, "NullLogger should not create any files"


class TestFileRetrievalLogger:
    """FileRetrievalLogger writes JSONL to disk."""

    @pytest.mark.asyncio
    async def test_single_call_writes_one_line(self, tmp_path):
        """log_ranking_event writes exactly one JSONL line."""
        log_path = str(tmp_path / "retrieval.jsonl")
        logger = FileRetrievalLogger(log_path)
        event = make_event()
        await logger.log_ranking_event(event)

        with open(log_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_two_calls_write_two_lines(self, tmp_path):
        """Second call to log_ranking_event writes a second line."""
        log_path = str(tmp_path / "retrieval.jsonl")
        logger = FileRetrievalLogger(log_path)
        await logger.log_ranking_event(make_event(turn_number=1))
        await logger.log_ranking_event(make_event(turn_number=2))

        with open(log_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_line_deserializes_to_dict(self, tmp_path):
        """Written line deserializes to dict with expected keys."""
        log_path = str(tmp_path / "retrieval.jsonl")
        logger = FileRetrievalLogger(log_path)
        event = make_event(session_id="test-session", active_k=7)
        await logger.log_ranking_event(event)

        with open(log_path, encoding="utf-8") as f:
            data = json.loads(f.readline())

        assert "session_id" in data
        assert "turn_number" in data
        assert "active_k" in data
        assert "fallback_tier" in data
        assert "router_enum_size" in data
        assert "scorer_latency_ms" in data

    @pytest.mark.asyncio
    async def test_line_contains_correct_values(self, tmp_path):
        """Written line contains correct field values from RankingEvent."""
        log_path = str(tmp_path / "retrieval.jsonl")
        logger = FileRetrievalLogger(log_path)
        event = make_event(
            session_id="my-session",
            turn_number=3,
            active_k=12,
            fallback_tier=2,
            router_enum_size=88,
            scorer_latency_ms=7.5,
        )
        await logger.log_ranking_event(event)

        with open(log_path, encoding="utf-8") as f:
            data = json.loads(f.readline())

        assert data["session_id"] == "my-session"
        assert data["turn_number"] == 3
        assert data["active_k"] == 12
        assert data["fallback_tier"] == 2
        assert data["router_enum_size"] == 88
        assert data["scorer_latency_ms"] == pytest.approx(7.5)

    @pytest.mark.asyncio
    async def test_creates_parent_directory(self, tmp_path):
        """FileRetrievalLogger creates parent directories if they don't exist."""
        log_path = str(tmp_path / "logs" / "sub" / "retrieval.jsonl")
        logger = FileRetrievalLogger(log_path)
        event = make_event()
        await logger.log_ranking_event(event)
        assert os.path.exists(log_path)

    @pytest.mark.asyncio
    async def test_appends_across_instances(self, tmp_path):
        """Multiple FileRetrievalLogger instances append to the same file."""
        log_path = str(tmp_path / "retrieval.jsonl")
        logger1 = FileRetrievalLogger(log_path)
        logger2 = FileRetrievalLogger(log_path)

        await logger1.log_ranking_event(make_event(session_id="s1"))
        await logger2.log_ranking_event(make_event(session_id="s2"))

        with open(log_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_other_methods_are_no_ops(self, tmp_path):
        """log_retrieval, log_retrieval_miss, log_tool_sequence are no-ops."""
        from src.multimcp.retrieval.models import RetrievalContext, ScoredTool
        from src.multimcp.mcp_proxy import ToolMapping
        from mcp import types

        log_path = str(tmp_path / "retrieval.jsonl")
        logger = FileRetrievalLogger(log_path)
        ctx = RetrievalContext(session_id="s", query="q")

        await logger.log_retrieval(ctx, [], 1.0)
        await logger.log_retrieval_miss("some_tool", ctx)
        await logger.log_tool_sequence("s", "tool_a", "tool_b")

        # No file should have been written (or file is empty)
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                content = f.read().strip()
            assert content == "", "Other methods should not write to log"


class TestFileRetrievalLoggerImport:
    """FileRetrievalLogger importable from logging module."""

    def test_importable(self):
        """FileRetrievalLogger can be imported from logging module."""
        from src.multimcp.retrieval.logging import FileRetrievalLogger
        assert FileRetrievalLogger is not None

    def test_is_subclass_of_retrieval_logger(self):
        """FileRetrievalLogger is a subclass of RetrievalLogger."""
        from src.multimcp.retrieval.logging import FileRetrievalLogger, RetrievalLogger
        assert issubclass(FileRetrievalLogger, RetrievalLogger)
