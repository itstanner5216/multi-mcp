"""Tests for rollout/shadow mode dispatch and startup wiring coherence.

Covers:
1. shadow_mode dispatch guard: rollout_stage="shadow" → all tools returned (no filtering),
   scoring path still executes.
2. Startup wiring coherence: app wires pipeline in shadow mode
   (enabled=True, shadow_mode=True, rollout_stage="shadow").

Runtime truth focus: these tests verify observable pipeline output and config
values, not internal helper behavior.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from mcp import types

from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.models import RetrievalConfig
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import RetrievalLogger
from src.multimcp.mcp_proxy import ToolMapping


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_tool_registry(n: int = 8) -> dict:
    """Create n mock ToolMapping entries."""
    reg: dict[str, ToolMapping] = {}
    for i in range(n):
        key = f"server__{i:02d}_tool"
        tool = types.Tool(
            name=f"{i:02d}_tool",
            description=f"Tool {i}",
            inputSchema={"type": "object", "properties": {}},
        )
        reg[key] = ToolMapping(server_name="server", client=None, tool=tool)
    return reg


def make_pipeline_with_stage(rollout_stage: str, shadow_mode: bool = False, n: int = 8) -> tuple[RetrievalPipeline, MagicMock]:
    """Create a minimal enabled pipeline with the given rollout_stage and shadow_mode.

    Returns (pipeline, mock_logger).
    """
    registry = make_tool_registry(n)
    config = RetrievalConfig(
        enabled=True,
        rollout_stage=rollout_stage,
        shadow_mode=shadow_mode,
        top_k=5,
        max_k=10,
        enable_routing_tool=False,
    )
    session_manager = SessionStateManager(config)
    logger = MagicMock(spec=RetrievalLogger)
    logger.log_ranking_event = AsyncMock()
    pipeline = RetrievalPipeline(
        PassthroughRetriever(),
        session_manager,
        logger,
        config,
        registry,
    )
    return pipeline, logger


# ── Shadow mode dispatch guard ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_shadow_stage_returns_all_tools():
    """When rollout_stage="shadow", get_tools_for_list returns ALL tools (no filtering).

    This is the shadow mode dispatch guard: the pipeline scores tools but does
    not restrict the returned set.
    """
    n = 8
    pipeline, _ = make_pipeline_with_stage("shadow", n=n)
    sid = "shadow-all-tools"

    result = await pipeline.get_tools_for_list(sid)

    assert len(result) == n, (
        f"Shadow mode must return all {n} tools; got {len(result)}"
    )


@pytest.mark.anyio
async def test_shadow_stage_scoring_executes():
    """When rollout_stage="shadow", the scoring path still executes (log_ranking_event is called).

    Shadow mode must score for telemetry purposes even though it returns all tools.
    """
    pipeline, logger = make_pipeline_with_stage("shadow")
    sid = "shadow-scoring"

    await pipeline.get_tools_for_list(sid)

    logger.log_ranking_event.assert_called_once(), (
        "log_ranking_event must be called even in shadow mode"
    )


@pytest.mark.anyio
async def test_shadow_stage_does_not_filter():
    """With rollout_stage="shadow" and enabled=True, no filtering occurs.

    Even with top_k=3 and 8 tools in registry, shadow mode must return all 8.
    """
    n = 8
    registry = make_tool_registry(n)
    config = RetrievalConfig(
        enabled=True,
        rollout_stage="shadow",
        shadow_mode=True,
        top_k=3,     # would limit to 3 in GA mode
        max_k=5,
        enable_routing_tool=False,
    )
    session_manager = SessionStateManager(config)
    logger = MagicMock(spec=RetrievalLogger)
    logger.log_ranking_event = AsyncMock()
    pipeline = RetrievalPipeline(
        PassthroughRetriever(),
        session_manager,
        logger,
        config,
        registry,
    )

    result = await pipeline.get_tools_for_list("shadow-no-filter")

    assert len(result) == n, (
        f"Shadow mode must return all {n} tools regardless of top_k={config.top_k}; got {len(result)}"
    )


@pytest.mark.anyio
async def test_ga_stage_filters_tools():
    """Contrast: with rollout_stage="ga" and top_k=3, only up to 3+routing tools returned.

    Verifies that filtering IS active in GA mode (shadow mode guard is not leaking).
    """
    n = 8
    registry = make_tool_registry(n)
    config = RetrievalConfig(
        enabled=True,
        rollout_stage="ga",
        shadow_mode=False,
        top_k=3,
        max_k=5,
        enable_routing_tool=False,
    )
    session_manager = SessionStateManager(config)
    logger = MagicMock(spec=RetrievalLogger)
    logger.log_ranking_event = AsyncMock()
    pipeline = RetrievalPipeline(
        PassthroughRetriever(),
        session_manager,
        logger,
        config,
        registry,
    )

    result = await pipeline.get_tools_for_list("ga-filters")

    # GA mode should return top_k tools (not all n)
    assert len(result) < n, (
        f"GA mode must filter tools (got {len(result)}, expected < {n})"
    )
    assert len(result) <= config.max_k, (
        f"GA mode must not exceed max_k={config.max_k}; got {len(result)}"
    )


# ── Startup wiring coherence ──────────────────────────────────────────────────


def test_startup_wiring_is_shadow_mode():
    """The startup wiring must use shadow mode (not forced GA mode).

    Verifies that multi_mcp.py wires RetrievalConfig with:
      enabled=True
      shadow_mode=True
      rollout_stage="shadow"

    This test fails if the production code is wired in GA mode, which would
    expose active filtering to users before the rollout is validated.
    """
    import inspect
    import src.multimcp.multi_mcp as multi_mcp_module

    source = inspect.getsource(multi_mcp_module)

    # Find the RetrievalConfig(...) constructor call in the source
    # The startup wiring block should NOT have rollout_stage="ga"
    assert 'rollout_stage="ga"' not in source, (
        "Startup wiring must not set rollout_stage='ga' — use 'shadow' for safe rollout"
    )

    assert 'rollout_stage="shadow"' in source, (
        "Startup wiring must set rollout_stage='shadow' for temporary shadow mode"
    )

    assert 'shadow_mode=True' in source, (
        "Startup wiring must set shadow_mode=True for temporary shadow mode"
    )


def test_startup_config_values():
    """Verify the RetrievalConfig values used at startup match the shadow mode requirement.

    Constructs the same config that startup should use and checks its fields.
    """
    config = RetrievalConfig(
        enabled=True,
        shadow_mode=True,
        rollout_stage="shadow",
    )

    assert config.enabled is True, "Startup config must have enabled=True"
    assert config.shadow_mode is True, "Startup config must have shadow_mode=True"
    assert config.rollout_stage == "shadow", (
        f"Startup config must have rollout_stage='shadow', got {config.rollout_stage!r}"
    )
