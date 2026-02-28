"""Abstract base classes for retrieval pipeline components."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .models import RetrievalContext, ScoredTool

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping


class ToolRetriever(ABC):
    """Abstract interface for tool retrieval strategies."""

    @abstractmethod
    async def retrieve(
        self,
        context: RetrievalContext,
        candidates: list["ToolMapping"],
    ) -> list[ScoredTool]:
        """Score and filter candidate tools based on context.

        Implementations MUST NOT modify tool_to_server — read-only consumers.
        Returns scored subset ordered by relevance.
        """
        ...


class PassthroughRetriever(ToolRetriever):
    """Returns all candidates with score=1.0. Used when no retriever configured."""

    async def retrieve(
        self,
        context: RetrievalContext,
        candidates: list["ToolMapping"],
    ) -> list[ScoredTool]:
        return [
            ScoredTool(
                tool_key=f"passthrough_{i}",
                tool_mapping=m,
                score=1.0,
                tier="full",
            )
            for i, m in enumerate(candidates)
        ]
