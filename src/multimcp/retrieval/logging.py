"""Abstract logging interface for retrieval pipeline events."""

from __future__ import annotations

import dataclasses
import json
import pathlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .models import RetrievalContext, ScoredTool

if TYPE_CHECKING:
    from .models import RankingEvent


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

    @abstractmethod
    async def log_ranking_event(self, event: "RankingEvent") -> None: ...


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

    async def log_ranking_event(self, event: "RankingEvent") -> None:
        pass


class FileRetrievalLogger(RetrievalLogger):
    """Appends structured RankingEvents as JSONL. One line per call.

    Other abstract methods are no-ops; RankingEvent is the primary log unit.
    """

    def __init__(self, log_path: str) -> None:
        self._path = pathlib.Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def log_ranking_event(self, event: "RankingEvent") -> None:
        line = json.dumps(dataclasses.asdict(event), default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

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
