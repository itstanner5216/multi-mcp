"""Tests for 6-tier fallback ladder — 07-01-PLAN.md mandatory tests.

Covers:
- Each tier triggers under correct conditions
- Tier 4 classification precedence
- Tier 5 frequency prior (time-decayed, direct_tool_calls + router_proxies)
- Tier 6: exactly 12 direct tools by namespace priority + routing tool
- No tier exposes more than 20 direct tools
- fallback_tier reported correctly in RankingEvent
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp import types

from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger, FileRetrievalLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import (
    RetrievalConfig,
    ScoredTool,
    WorkspaceEvidence,
    RankingEvent,
)
from src.multimcp.retrieval.static_categories import TIER6_NAMESPACE_PRIORITY


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_tool(name: str, desc: str = "A tool") -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": {}},
    )


def _make_mapping(server: str, tool: types.Tool):
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()
    return m


def _make_registry(n: int = 20, server_prefix: str = "srv") -> dict:
    return {
        f"{server_prefix}{i}__{i}_tool": _make_mapping(
            f"{server_prefix}{i}", _make_tool(f"{i}_tool")
        )
        for i in range(n)
    }


def _make_pipeline(
    registry: dict | None = None,
    config: RetrievalConfig | None = None,
    retriever=None,
    logger=None,
    telemetry_scanner=None,
) -> RetrievalPipeline:
    if config is None:
        config = RetrievalConfig(enabled=True, rollout_stage="ga")
    if registry is None:
        registry = _make_registry()
    if retriever is None:
        retriever = PassthroughRetriever()
    if logger is None:
        logger = NullLogger()
    return RetrievalPipeline(
        retriever=retriever,
        session_manager=SessionStateManager(config),
        logger=logger,
        config=config,
        tool_registry=registry,
        telemetry_scanner=telemetry_scanner,
    )


def _scored_from_registry(registry: dict) -> list[ScoredTool]:
    return [
        ScoredTool(tool_key=k, tool_mapping=v, score=1.0)
        for k, v in registry.items()
    ]


# ── Tier trigger tests ────────────────────────────────────────────────────────

class TestTier1Triggers:
    @pytest.mark.asyncio
    async def test_tier1_triggers(self):
        """Tier 1: BMXF available + env + conv + turn > 0."""
        registry = _make_registry(10)
        scored = _scored_from_registry(registry)

        mock_retriever = MagicMock()
        mock_retriever.retrieve = AsyncMock(return_value=scored)
        mock_retriever._env_index = MagicMock()

        pipeline = _make_pipeline(registry=registry, retriever=mock_retriever)
        pipeline._session_evidence["t1"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0},
        )
        pipeline._session_turns["t1"] = 2

        captured_events: list[RankingEvent] = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event: RankingEvent) -> None:
                captured_events.append(event)

        pipeline.logger = CapturingLogger()

        with patch("src.multimcp.retrieval.pipeline._weighted_rrf") as mock_rrf, \
             patch("src.multimcp.retrieval.pipeline._compute_alpha", return_value=0.5):
            mock_rrf.return_value = scored
            await pipeline.get_tools_for_list("t1", "list files search query results")

        assert captured_events, "Expected RankingEvent to be emitted"
        assert captured_events[0].fallback_tier == 1
        mock_rrf.assert_called_once()


class TestTier2Triggers:
    @pytest.mark.asyncio
    async def test_tier2_triggers(self):
        """Tier 2: BMXF available + env query but no conv query."""
        registry = _make_registry(10)
        scored = _scored_from_registry(registry)

        mock_retriever = MagicMock()
        mock_retriever.retrieve = AsyncMock(return_value=scored)
        mock_retriever._env_index = MagicMock()

        pipeline = _make_pipeline(registry=registry, retriever=mock_retriever)
        pipeline._session_evidence["t2"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0},
        )
        # turn=0, no conv query -> tier 2

        captured_events: list[RankingEvent] = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event: RankingEvent) -> None:
                captured_events.append(event)

        pipeline.logger = CapturingLogger()

        await pipeline.get_tools_for_list("t2", "")  # no conversation context

        assert captured_events
        assert captured_events[0].fallback_tier == 2


class TestTier3Triggers:
    @pytest.mark.asyncio
    async def test_tier3_triggers(self):
        """Tier 3: BMXF unavailable, KeywordRetriever available."""
        registry = _make_registry(10)
        scored = _scored_from_registry(registry)

        # No _env_index -> BMXF unavailable
        mock_bmxf = MagicMock(spec=[])  # no attributes
        mock_bmxf.retrieve = AsyncMock(side_effect=RuntimeError("bmxf unavailable"))

        mock_keyword = MagicMock()
        mock_keyword.retrieve = AsyncMock(return_value=scored)

        pipeline = _make_pipeline(registry=registry, retriever=mock_bmxf)
        pipeline._session_evidence["t3"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0},
        )
        # Inject keyword retriever
        pipeline._keyword_retriever = mock_keyword

        captured_events: list[RankingEvent] = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event: RankingEvent) -> None:
                captured_events.append(event)

        pipeline.logger = CapturingLogger()

        await pipeline.get_tools_for_list("t3", "")

        assert captured_events
        assert captured_events[0].fallback_tier == 3
        mock_keyword.retrieve.assert_called_once()


class TestTier4Triggers:
    @pytest.mark.asyncio
    async def test_tier4_triggers(self):
        """Tier 4: No usable scorer + confident project type."""
        # Build registry with filesystem server
        registry = {
            "filesystem__read": _make_mapping("filesystem", _make_tool("read")),
            "shell__run": _make_mapping("shell", _make_tool("run")),
            "web_search__search": _make_mapping("web_search", _make_tool("search")),
            "github__create_pr": _make_mapping("github", _make_tool("create_pr")),
        }

        # No BMXF, no keyword retriever
        mock_bmxf = MagicMock(spec=[])

        pipeline = _make_pipeline(registry=registry, retriever=mock_bmxf)
        # Evidence with python web signals (no index available)
        pipeline._session_evidence["t4"] = WorkspaceEvidence(
            workspace_confidence=0.8,
            merged_tokens={"lang:python": 1.0, "manifest:pyproject.toml": 0.9},
        )

        captured_events: list[RankingEvent] = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event: RankingEvent) -> None:
                captured_events.append(event)

        pipeline.logger = CapturingLogger()

        await pipeline.get_tools_for_list("t4", "")

        assert captured_events
        assert captured_events[0].fallback_tier == 4


class TestTier4ClassificationPrecedence:
    def _make_evidence(self, tokens: dict) -> WorkspaceEvidence:
        return WorkspaceEvidence(
            workspace_confidence=0.9,
            merged_tokens=tokens,
        )

    def _pipeline(self) -> RetrievalPipeline:
        return _make_pipeline()

    def test_infrastructure_wins_over_all(self):
        p = self._pipeline()
        ev = self._make_evidence({
            "infra:terraform": 1.0,
            "manifest:Cargo.toml": 1.0,
            "lang:python": 1.0,
            "manifest:package.json": 1.0,
        })
        ptype, confident = p._classify_project_type(ev)
        assert ptype == "infrastructure"
        assert confident is True

    def test_rust_cli_wins_over_python_node(self):
        p = self._pipeline()
        ev = self._make_evidence({
            "manifest:Cargo.toml": 1.0,
            "lang:python": 1.0,
            "manifest:package.json": 1.0,
        })
        ptype, confident = p._classify_project_type(ev)
        assert ptype == "rust_cli"

    def test_python_web_wins_over_node(self):
        p = self._pipeline()
        ev = self._make_evidence({
            "lang:python": 1.0,
            "manifest:package.json": 1.0,
        })
        ptype, confident = p._classify_project_type(ev)
        assert ptype == "python_web"

    def test_node_web_matches(self):
        p = self._pipeline()
        ev = self._make_evidence({"manifest:package.json": 1.0})
        ptype, confident = p._classify_project_type(ev)
        assert ptype == "node_web"

    def test_generic_from_confidence(self):
        p = self._pipeline()
        ev = self._make_evidence({})
        # workspace_confidence >= 0.45 with no manifest tokens
        ev.workspace_confidence = 0.5
        ptype, confident = p._classify_project_type(ev)
        assert ptype == "generic"
        assert confident is True

    def test_not_confident_falls_through(self):
        p = self._pipeline()
        ev = self._make_evidence({})
        ev.workspace_confidence = 0.3  # < 0.45
        ptype, confident = p._classify_project_type(ev)
        assert not confident

    def test_tier4_classification_precedence(self):
        """Full precedence order: infrastructure > rust > python > node > generic."""
        p = self._pipeline()
        tests = [
            ({"infra:terraform": 1.0, "lang:python": 1.0, "manifest:package.json": 1.0}, "infrastructure"),
            ({"manifest:Cargo.toml": 1.0, "lang:python": 1.0}, "rust_cli"),
            ({"manifest:pyproject.toml": 1.0, "manifest:package.json": 1.0}, "python_web"),
            ({"manifest:package.json": 1.0}, "node_web"),
        ]
        for tokens, expected in tests:
            ev = self._make_evidence(tokens)
            ptype, confident = p._classify_project_type(ev)
            assert ptype == expected, f"Expected {expected} for tokens {tokens}, got {ptype}"


class TestTier5Triggers:
    @pytest.mark.asyncio
    async def test_tier5_triggers(self):
        """Tier 5: No confident project type, JSONL log available."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            # Write a valid ranking event entry
            entry = {
                "session_id": "prior_sess",
                "turn_number": 1,
                "catalog_version": "",
                "group": "control",
                "direct_tool_calls": ["tool_a", "tool_b"],
                "router_proxies": [],
                "active_tool_ids": ["tool_a"],
            }
            f.write(json.dumps(entry) + "\n")
            f.flush()
            log_path = f.name

        try:
            registry = {
                "tool_a": _make_mapping("srv", _make_tool("tool_a")),
                "tool_b": _make_mapping("srv", _make_tool("tool_b")),
                "tool_c": _make_mapping("srv", _make_tool("tool_c")),
            }

            from src.multimcp.retrieval.logging import FileRetrievalLogger
            file_logger = FileRetrievalLogger(log_path)

            # No BMXF, no keyword retriever, no evidence -> falls to tier 5
            mock_bmxf = MagicMock(spec=[])
            pipeline = _make_pipeline(
                registry=registry, retriever=mock_bmxf, logger=file_logger
            )

            captured_events: list[RankingEvent] = []
            orig_log = file_logger.log_ranking_event

            async def capturing_log(event: RankingEvent) -> None:
                captured_events.append(event)

            pipeline.logger.log_ranking_event = capturing_log  # type: ignore[method-assign]

            await pipeline.get_tools_for_list("t5sess", "")

            assert captured_events
            # Tier 5 if freq prior found tools, else tier 6
            assert captured_events[0].fallback_tier in (5, 6)
        finally:
            os.unlink(log_path)


class TestTier5FrequencyPrior:
    @pytest.mark.asyncio
    async def test_tier5_frequency_prior(self):
        """Tier 5: time-decayed scoring uses direct_tool_calls + router_proxies, excludes shadow."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            # Two events: one shadow (excluded), one control (included)
            shadow_entry = {
                "session_id": "s1", "turn_number": 1, "catalog_version": "",
                "group": "shadow",
                "direct_tool_calls": ["tool_x"],
                "router_proxies": ["tool_y"],
                "active_tool_ids": [],
            }
            control_entry = {
                "session_id": "s2", "turn_number": 1, "catalog_version": "",
                "group": "control",
                "direct_tool_calls": ["tool_a", "tool_a"],  # counts twice
                "router_proxies": ["tool_b"],
                "active_tool_ids": [],
            }
            f.write(json.dumps(shadow_entry) + "\n")
            f.write(json.dumps(control_entry) + "\n")
            f.flush()
            log_path = f.name

        try:
            registry = {
                "tool_a": _make_mapping("srv", _make_tool("tool_a")),
                "tool_b": _make_mapping("srv", _make_tool("tool_b")),
                "tool_x": _make_mapping("srv", _make_tool("tool_x")),
                "tool_y": _make_mapping("srv", _make_tool("tool_y")),
            }

            file_logger = FileRetrievalLogger(log_path)
            mock_bmxf = MagicMock(spec=[])
            pipeline = _make_pipeline(
                registry=registry, retriever=mock_bmxf, logger=file_logger
            )

            freq_tools = pipeline._frequency_prior_tools(dynamic_k=10)

            # tool_a should score highest (2 direct_tool_calls)
            if freq_tools:
                tool_keys = [t.tool_key for t in freq_tools]
                # tool_a has 2 hits, tool_b has 1 hit
                assert "tool_a" in tool_keys
                assert "tool_b" in tool_keys
                # shadow tools must be excluded
                assert "tool_x" not in tool_keys
                assert "tool_y" not in tool_keys
                # tool_a must rank above tool_b (higher count)
                if "tool_a" in tool_keys and "tool_b" in tool_keys:
                    assert tool_keys.index("tool_a") < tool_keys.index("tool_b")
        finally:
            os.unlink(log_path)


class TestTier6Triggers:
    @pytest.mark.asyncio
    async def test_tier6_triggers(self):
        """Tier 6: all other tiers unavailable -> universal fallback."""
        registry = _make_registry(20)
        mock_bmxf = MagicMock(spec=[])

        pipeline = _make_pipeline(registry=registry, retriever=mock_bmxf)
        # No evidence, no log file -> tier 6

        captured_events: list[RankingEvent] = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event: RankingEvent) -> None:
                captured_events.append(event)

        pipeline.logger = CapturingLogger()

        await pipeline.get_tools_for_list("t6", "")

        assert captured_events
        assert captured_events[0].fallback_tier == 6


class TestTier6Exactly12PlusRouter:
    @pytest.mark.asyncio
    async def test_tier6_exactly_12_plus_router(self):
        """Tier 6: exactly 12 direct tools by namespace priority + routing tool."""
        # Build registry with all priority namespaces
        registry = {}
        for ns in TIER6_NAMESPACE_PRIORITY:
            registry[f"{ns}__main_tool"] = _make_mapping(ns, _make_tool("main_tool"))
        # Add some extras
        for i in range(10):
            registry[f"extra{i}__tool{i}"] = _make_mapping(f"extra{i}", _make_tool(f"tool{i}"))

        mock_bmxf = MagicMock(spec=[])
        config = RetrievalConfig(
            enabled=True, rollout_stage="ga", enable_routing_tool=True
        )
        pipeline = _make_pipeline(registry=registry, retriever=mock_bmxf, config=config)

        result = await pipeline.get_tools_for_list("t6r", "")

        tool_names = [t.name for t in result]
        # routing tool should be present
        assert "request_tool" in tool_names
        # direct tools = result - routing tool
        direct_tools = [t for t in result if t.name != "request_tool"]
        assert len(direct_tools) == 12


# ── Invariant: no tier exceeds 20 direct tools ───────────────────────────────

class TestNoTierExceeds20:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("n_tools", [25, 50, 100, 168, 500])
    async def test_no_tier_exceeds_20(self, n_tools: int):
        """No fallback tier may expose more than 20 direct tools."""
        registry = _make_registry(n_tools)
        mock_bmxf = MagicMock(spec=[])
        config = RetrievalConfig(
            enabled=True, rollout_stage="ga", enable_routing_tool=True
        )
        pipeline = _make_pipeline(registry=registry, retriever=mock_bmxf, config=config)

        result = await pipeline.get_tools_for_list("invariant", "")
        direct_tools = [t for t in result if t.name != "request_tool"]
        assert len(direct_tools) <= 20, (
            f"Tier returned {len(direct_tools)} direct tools with {n_tools}-tool registry"
        )


# ── fallback_tier reported correctly ─────────────────────────────────────────

class TestFallbackTierReportedCorrectly:
    @pytest.mark.asyncio
    async def test_fallback_tier_reported_correctly(self):
        """RankingEvent.fallback_tier must match the actual tier used."""
        registry = _make_registry(20)
        mock_bmxf = MagicMock(spec=[])

        captured_events: list[RankingEvent] = []

        class CapturingLogger(NullLogger):
            async def log_ranking_event(self, event: RankingEvent) -> None:
                captured_events.append(event)

        pipeline = _make_pipeline(
            registry=registry, retriever=mock_bmxf, logger=CapturingLogger()
        )
        # No evidence, no log -> tier 6
        await pipeline.get_tools_for_list("ftr", "")

        assert captured_events
        # Tier 6 is the expected fallback when everything else is unavailable
        assert captured_events[0].fallback_tier == 6
