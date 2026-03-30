"""Tests for roots/telemetry wiring — 07-01-PLAN.md mandatory tests.

Covers:
- roots/list request reaches pipeline.set_session_roots()
- roots/list_changed notification triggers re-request + updated evidence
- set_session_roots() runs telemetry scanner and caches WorkspaceEvidence
- Client without roots capability falls through to fallback ladder
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp import types

from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import (
    RetrievalConfig,
    WorkspaceEvidence,
    RootEvidence,
)


def _make_registry(n: int = 5) -> dict:
    from mcp import types as t
    registry = {}
    for i in range(n):
        m = MagicMock()
        m.server_name = f"srv{i}"
        m.tool = t.Tool(
            name=f"tool{i}",
            description="desc",
            inputSchema={"type": "object", "properties": {}},
        )
        m.client = MagicMock()
        registry[f"srv{i}__tool{i}"] = m
    return registry


def _make_pipeline(
    registry: dict | None = None,
    config: RetrievalConfig | None = None,
    scanner=None,
) -> RetrievalPipeline:
    if config is None:
        config = RetrievalConfig(enabled=True, rollout_stage="ga", enable_telemetry=True)
    if registry is None:
        registry = _make_registry()
    return RetrievalPipeline(
        retriever=PassthroughRetriever(),
        session_manager=SessionStateManager(config),
        logger=NullLogger(),
        config=config,
        tool_registry=registry,
        telemetry_scanner=scanner,
    )


class TestRootsListToSetSessionRoots:
    @pytest.mark.asyncio
    async def test_roots_list_to_set_session_roots(self):
        """Mock roots/list response must reach pipeline.set_session_roots().

        Simulates mcp_proxy._request_and_set_roots() being called with root URIs
        and verifies that set_session_roots() stores them.
        """
        pipeline = _make_pipeline()

        root_uris = ["file:///home/user/project", "file:///home/user/lib"]
        await pipeline.set_session_roots("sess_roots", root_uris)

        # Roots must be stored
        assert pipeline._session_roots.get("sess_roots") == root_uris

    @pytest.mark.asyncio
    async def test_roots_list_to_set_session_roots_via_proxy(self):
        """mcp_proxy._request_and_set_roots() calls pipeline.set_session_roots()."""
        from src.multimcp.mcp_proxy import MCPProxyServer
        from src.multimcp.mcp_client import MCPClientManager

        # Build a minimal proxy with a mock pipeline
        client_manager = MagicMock(spec=MCPClientManager)
        client_manager.clients = {}
        proxy = MCPProxyServer(client_manager)

        mock_pipeline = MagicMock()
        mock_pipeline.set_session_roots = AsyncMock()
        proxy.retrieval_pipeline = mock_pipeline

        # Mock server session that returns roots
        mock_session = MagicMock()
        mock_root = MagicMock()
        mock_root.uri = "file:///home/user/project"
        mock_list_result = MagicMock()
        mock_list_result.roots = [mock_root]
        mock_session.list_roots = AsyncMock(return_value=mock_list_result)
        proxy._server_session = mock_session

        await proxy._request_and_set_roots("test_session")

        mock_pipeline.set_session_roots.assert_called_once_with(
            "test_session", ["file:///home/user/project"]
        )


class TestRootsListChangedRefresh:
    @pytest.mark.asyncio
    async def test_roots_list_changed_refresh(self):
        """roots/list_changed notification triggers re-request and updated evidence."""
        from src.multimcp.mcp_proxy import MCPProxyServer
        from src.multimcp.mcp_client import MCPClientManager

        client_manager = MagicMock(spec=MCPClientManager)
        client_manager.clients = {}
        proxy = MCPProxyServer(client_manager)

        call_count = 0
        captured_uris: list[list[str]] = []

        class TrackingPipeline:
            async def set_session_roots(self, session_id: str, uris: list[str]) -> None:
                nonlocal call_count
                call_count += 1
                captured_uris.append(uris)

        proxy.retrieval_pipeline = TrackingPipeline()

        # First roots/list: one root
        mock_session = MagicMock()
        mock_root1 = MagicMock()
        mock_root1.uri = "file:///project"
        mock_result1 = MagicMock()
        mock_result1.roots = [mock_root1]
        mock_session.list_roots = AsyncMock(return_value=mock_result1)
        proxy._server_session = mock_session

        await proxy._request_and_set_roots("sess_changed")
        assert call_count == 1
        assert captured_uris[0] == ["file:///project"]

        # Simulate roots/list_changed: two roots now
        mock_root2 = MagicMock()
        mock_root2.uri = "file:///lib"
        mock_result2 = MagicMock()
        mock_result2.roots = [mock_root1, mock_root2]
        mock_session.list_roots = AsyncMock(return_value=mock_result2)

        await proxy._handle_roots_list_changed(None)  # notification handler
        assert call_count == 2
        assert captured_uris[1] == ["file:///project", "file:///lib"]


class TestSetSessionRootsRunsScanner:
    @pytest.mark.asyncio
    async def test_set_session_roots_runs_scanner(self):
        """set_session_roots() must run telemetry scanner and cache WorkspaceEvidence."""
        mock_scanner = MagicMock()
        mock_evidence = WorkspaceEvidence(
            workspace_confidence=0.9,
            merged_tokens={"lang:python": 1.0, "manifest:pyproject.toml": 0.8},
        )
        mock_scanner.scan_roots = MagicMock(return_value=mock_evidence)

        pipeline = _make_pipeline(scanner=mock_scanner)

        root_uris = ["file:///home/user/myproject"]
        await pipeline.set_session_roots("scan_sess", root_uris)

        # Scanner must have been called
        mock_scanner.scan_roots.assert_called_once_with(root_uris)

        # Evidence must be cached
        cached = pipeline._session_evidence.get("scan_sess")
        assert cached is not None
        assert cached.workspace_confidence == 0.9
        assert "lang:python" in cached.merged_tokens

    @pytest.mark.asyncio
    async def test_set_session_roots_no_scanner(self):
        """set_session_roots() with no scanner must store roots but not crash."""
        pipeline = _make_pipeline(scanner=None)

        await pipeline.set_session_roots("noscan", ["file:///project"])

        # Roots stored
        assert pipeline._session_roots.get("noscan") == ["file:///project"]
        # No evidence (scanner not available)
        assert "noscan" not in pipeline._session_evidence

    @pytest.mark.asyncio
    async def test_set_session_roots_telemetry_disabled(self):
        """set_session_roots() with enable_telemetry=False must not run scanner."""
        mock_scanner = MagicMock()
        mock_scanner.scan_roots = MagicMock()

        config = RetrievalConfig(enabled=True, enable_telemetry=False, rollout_stage="ga")
        registry = _make_registry()
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
            telemetry_scanner=mock_scanner,
        )

        await pipeline.set_session_roots("tdisabled", ["file:///project"])
        mock_scanner.scan_roots.assert_not_called()


class TestNoRootsFallsThrough:
    @pytest.mark.asyncio
    async def test_no_roots_falls_through_to_fallback(self):
        """Client without roots support falls through to fallback ladder (not an error)."""
        from src.multimcp.mcp_proxy import MCPProxyServer
        from src.multimcp.mcp_client import MCPClientManager

        client_manager = MagicMock(spec=MCPClientManager)
        client_manager.clients = {}
        proxy = MCPProxyServer(client_manager)

        # Session raises on list_roots (no roots capability)
        mock_session = MagicMock()
        mock_session.list_roots = AsyncMock(side_effect=Exception("roots not supported"))
        proxy._server_session = mock_session

        set_roots_called = False

        class TrackingPipeline:
            async def set_session_roots(self, session_id: str, uris: list[str]) -> None:
                nonlocal set_roots_called
                set_roots_called = True

        proxy.retrieval_pipeline = TrackingPipeline()

        # Must not raise
        await proxy._request_and_set_roots("no_roots_sess")

        # Pipeline.set_session_roots must NOT have been called (roots failed)
        assert not set_roots_called

    @pytest.mark.asyncio
    async def test_pipeline_falls_through_without_evidence(self):
        """Pipeline returns valid tool list even with no roots evidence (via fallback)."""
        registry = _make_registry(10)
        pipeline = _make_pipeline(registry=registry)
        # No evidence for this session

        result = await pipeline.get_tools_for_list("noevidencesess", "")
        assert len(result) > 0  # Must return something (fallback ladder)
