"""Core data models for the retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from src.multimcp.mcp_proxy import ToolMapping


@dataclass
class RetrievalContext:
    """Carries the signal for retrieval operations."""
    session_id: str
    query: str = ""
    tool_call_history: list[str] = field(default_factory=list)
    server_hint: Optional[str] = None


@dataclass
class ScoredTool:
    """A tool with its retrieval score and tier assignment."""
    tool_key: str
    tool_mapping: "ToolMapping"
    score: float = 1.0
    tier: Literal["full", "summary"] = "full"


@dataclass
class RetrievalConfig:
    """Pipeline configuration with sensible defaults."""
    enabled: bool = False
    top_k: int = 10
    full_description_count: int = 3
    anchor_tools: list[str] = field(default_factory=list)
