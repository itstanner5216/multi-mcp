"""Abstract logging interface for retrieval pipeline events."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import anyio

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

    @abstractmethod
    async def log_alert(
        self,
        alert_name: str,
        message: str,
        details: dict[str, object] | None = None,
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

    async def log_ranking_event(self, event: "RankingEvent") -> None:
        pass

    async def log_alert(
        self,
        alert_name: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        pass


class FileRetrievalLogger(RetrievalLogger):
    """Appends structured RankingEvents as JSONL. One line per call.

    Other abstract methods are no-ops; RankingEvent is the primary log unit.
    File writes are offloaded to a worker thread to avoid blocking the event loop,
    and serialized with an async lock to prevent interleaved JSONL lines.
    """

    def __init__(self, log_path: str) -> None:
        self._path = pathlib.Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()

    def _sync_write(self, line: str) -> None:
        """Synchronous file append — run in worker thread only."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    async def log_ranking_event(self, event: "RankingEvent") -> None:
        line = json.dumps(dataclasses.asdict(event), default=str)
        async with self._write_lock:
            await anyio.to_thread.run_sync(self._sync_write, line)

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

    async def log_alert(
        self,
        alert_name: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        import time as _time
        record = {
            "type": "alert",
            "alert_name": alert_name,
            "message": message,
            "details": details or {},
            "timestamp": _time.time(),
        }
        line = json.dumps(record, default=str)
        async with self._write_lock:
            await anyio.to_thread.run_sync(self._sync_write, line)
