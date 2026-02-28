"""Abstract logging interface for retrieval pipeline events."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import RetrievalContext, ScoredTool


class RetrievalLogger(ABC):
    """Abstract interface for retrieval event logging."""

    @abstractmethod
    async def log_retrieval(
        self,
        context: RetrievalContext,
        results: list[ScoredTool],
        latency_ms: float,
    ) -> None: ...

    @abstractmethod
    async def log_retrieval_miss(
        self,
        tool_name: str,
        context: RetrievalContext,
    ) -> None: ...

    @abstractmethod
    async def log_tool_sequence(
        self,
        session_id: str,
        tool_a: str,
        tool_b: str,
    ) -> None: ...


class NullLogger(RetrievalLogger):
    """No-op logger. Default when no logger configured."""

    async def log_retrieval(
        self,
        context: RetrievalContext,
        results: list[ScoredTool],
        latency_ms: float,
    ) -> None:
        pass

    async def log_retrieval_miss(
        self,
        tool_name: str,
        context: RetrievalContext,
    ) -> None:
        pass

    async def log_tool_sequence(
        self,
        session_id: str,
        tool_a: str,
        tool_b: str,
    ) -> None:
        pass
