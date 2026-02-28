"""Tests for retrieval abstract interfaces and default implementations."""
import pytest
from unittest.mock import MagicMock
from src.multimcp.retrieval.base import PassthroughRetriever, ToolRetriever
from src.multimcp.retrieval.logging import NullLogger, RetrievalLogger
from src.multimcp.retrieval.models import RetrievalContext


class TestToolRetrieverABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ToolRetriever()

    @pytest.mark.asyncio
    async def test_passthrough_returns_all_candidates(self):
        retriever = PassthroughRetriever()
        candidates = [MagicMock() for _ in range(5)]
        ctx = RetrievalContext(session_id="test")
        results = await retriever.retrieve(ctx, candidates)
        assert len(results) == 5
        assert all(r.score == 1.0 for r in results)
        assert all(r.tier == "full" for r in results)

    @pytest.mark.asyncio
    async def test_passthrough_preserves_references(self):
        """Each ScoredTool must hold a reference to the original ToolMapping."""
        retriever = PassthroughRetriever()
        mock_mapping = MagicMock()
        ctx = RetrievalContext(session_id="test")
        results = await retriever.retrieve(ctx, [mock_mapping])
        assert results[0].tool_mapping is mock_mapping

    @pytest.mark.asyncio
    async def test_passthrough_empty_candidates(self):
        retriever = PassthroughRetriever()
        ctx = RetrievalContext(session_id="test")
        results = await retriever.retrieve(ctx, [])
        assert results == []

    @pytest.mark.asyncio
    async def test_passthrough_assigns_sequential_keys(self):
        retriever = PassthroughRetriever()
        candidates = [MagicMock() for _ in range(3)]
        ctx = RetrievalContext(session_id="test")
        results = await retriever.retrieve(ctx, candidates)
        keys = [r.tool_key for r in results]
        assert keys == ["passthrough_0", "passthrough_1", "passthrough_2"]


class TestRetrievalLoggerABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            RetrievalLogger()

    @pytest.mark.asyncio
    async def test_null_logger_log_retrieval_noop(self):
        logger = NullLogger()
        ctx = RetrievalContext(session_id="test")
        await logger.log_retrieval(ctx, [], 0.0)

    @pytest.mark.asyncio
    async def test_null_logger_log_miss_noop(self):
        logger = NullLogger()
        ctx = RetrievalContext(session_id="test")
        await logger.log_retrieval_miss("tool", ctx)

    @pytest.mark.asyncio
    async def test_null_logger_log_sequence_noop(self):
        logger = NullLogger()
        await logger.log_tool_sequence("s1", "a", "b")

    def test_null_logger_is_retrieval_logger(self):
        """NullLogger must be a proper subclass of RetrievalLogger."""
        logger = NullLogger()
        assert isinstance(logger, RetrievalLogger)

    def test_passthrough_is_tool_retriever(self):
        """PassthroughRetriever must be a proper subclass of ToolRetriever."""
        retriever = PassthroughRetriever()
        assert isinstance(retriever, ToolRetriever)
