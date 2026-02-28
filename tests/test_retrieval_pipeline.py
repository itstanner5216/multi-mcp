"""Tests for RetrievalPipeline orchestrator."""
import pytest
from unittest.mock import MagicMock
from mcp import types
from src.multimcp.retrieval.pipeline import RetrievalPipeline
from src.multimcp.retrieval.base import PassthroughRetriever
from src.multimcp.retrieval.logging import NullLogger
from src.multimcp.retrieval.session import SessionStateManager
from src.multimcp.retrieval.models import RetrievalConfig


def _make_tool(name: str, desc: str = "A tool") -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object", "properties": {}},
    )


def _make_mapping(server: str, tool: types.Tool):
    """Create a mock ToolMapping with the right attributes."""
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = MagicMock()  # Non-None = connected
    return m


def _make_disconnected_mapping(server: str, tool: types.Tool):
    """Create a mock ToolMapping with client=None (disconnected)."""
    m = MagicMock()
    m.server_name = server
    m.tool = tool
    m.client = None
    return m


class TestPipelineDisabled:
    """When retrieval is disabled, pipeline returns all tools."""

    @pytest.mark.asyncio
    async def test_returns_all_connected_tools(self):
        config = RetrievalConfig(enabled=False)
        registry = {
            "github__get_me": _make_mapping("github", _make_tool("get_me")),
            "exa__search": _make_mapping("exa", _make_tool("search")),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        tools = await pipeline.get_tools_for_list("session-1")
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_includes_cached_disconnected_tools(self):
        """Cached/disconnected tools (client=None) are included — they connect on demand."""
        config = RetrievalConfig(enabled=False)
        registry = {
            "github__get_me": _make_mapping("github", _make_tool("get_me")),
            "cached__tool": _make_disconnected_mapping("cached", _make_tool("tool")),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 2  # Both connected and cached/disconnected
        tool_names = {t.name for t in tools}
        assert tool_names == {"get_me", "tool"}

    @pytest.mark.asyncio
    async def test_returns_tool_objects(self):
        config = RetrievalConfig(enabled=False)
        tool = _make_tool("get_me")
        registry = {"github__get_me": _make_mapping("github", tool)}
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        tools = await pipeline.get_tools_for_list("s1")
        assert tools[0] is tool

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty(self):
        config = RetrievalConfig(enabled=False)
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry={},
        )
        tools = await pipeline.get_tools_for_list("s1")
        assert tools == []


class TestPipelineEnabled:
    """When retrieval is enabled, pipeline uses session state."""

    @pytest.mark.asyncio
    async def test_fresh_session_returns_only_anchors(self):
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
        )
        tool_get_me = _make_tool("get_me")
        tool_search = _make_tool("search")
        registry = {
            "github__get_me": _make_mapping("github", tool_get_me),
            "exa__search": _make_mapping("exa", tool_search),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 1
        assert tools[0].name == "get_me"

    @pytest.mark.asyncio
    async def test_disclosed_tools_appear(self):
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
        )
        tool_get_me = _make_tool("get_me")
        tool_search = _make_tool("search")
        registry = {
            "github__get_me": _make_mapping("github", tool_get_me),
            "exa__search": _make_mapping("exa", tool_search),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        # Simulate disclosure
        pipeline.session_manager.get_or_create_session("s1")
        pipeline.session_manager.add_tools("s1", ["exa__search"])
        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_enabled_includes_disconnected_anchors(self):
        """Disconnected anchor tools are still visible — they connect on demand."""
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me", "cached__tool"],
        )
        registry = {
            "github__get_me": _make_mapping("github", _make_tool("get_me")),
            "cached__tool": _make_disconnected_mapping("cached", _make_tool("tool")),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 2  # Both connected and cached/disconnected anchors
        tool_names = {t.name for t in tools}
        assert tool_names == {"get_me", "tool"}

    @pytest.mark.asyncio
    async def test_enabled_skips_missing_registry_keys(self):
        """If an anchor tool key isn't in the registry, skip it gracefully."""
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["nonexistent__tool"],
        )
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry={},
        )
        tools = await pipeline.get_tools_for_list("s1")
        assert tools == []

    @pytest.mark.asyncio
    async def test_on_tool_called_returns_false_placeholder(self):
        config = RetrievalConfig(enabled=True)
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry={},
        )
        result = await pipeline.on_tool_called("s1", "tool_name", {})
        assert result is False


class TestPipelineRegistryReference:
    """Pipeline must hold a reference to the registry, not a copy."""

    @pytest.mark.asyncio
    async def test_registry_is_reference_not_copy(self):
        config = RetrievalConfig(enabled=False)
        registry = {}
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        # Add tool after pipeline creation — pipeline must see it
        registry["new__tool"] = _make_mapping("new", _make_tool("tool"))
        tools = await pipeline.get_tools_for_list("s1")
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_registry_removal_reflected(self):
        config = RetrievalConfig(enabled=False)
        registry = {"a__tool": _make_mapping("a", _make_tool("tool"))}
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        del registry["a__tool"]
        tools = await pipeline.get_tools_for_list("s1")
        assert tools == []


class TestPipelineSessionLifecycle:
    """Verify session lifecycle through the pipeline."""

    @pytest.mark.asyncio
    async def test_repeated_calls_same_session(self):
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
        )
        registry = {"github__get_me": _make_mapping("github", _make_tool("get_me"))}
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        # First call creates session
        tools1 = await pipeline.get_tools_for_list("s1")
        # Second call reuses session
        tools2 = await pipeline.get_tools_for_list("s1")
        assert len(tools1) == len(tools2) == 1

    @pytest.mark.asyncio
    async def test_different_sessions_independent(self):
        config = RetrievalConfig(
            enabled=True,
            anchor_tools=["github__get_me"],
        )
        registry = {
            "github__get_me": _make_mapping("github", _make_tool("get_me")),
            "exa__search": _make_mapping("exa", _make_tool("search")),
        }
        pipeline = RetrievalPipeline(
            retriever=PassthroughRetriever(),
            session_manager=SessionStateManager(config),
            logger=NullLogger(),
            config=config,
            tool_registry=registry,
        )
        # Session 1 gets extra tool
        pipeline.session_manager.get_or_create_session("s1")
        pipeline.session_manager.add_tools("s1", ["exa__search"])
        # Session 2 doesn't
        tools_s1 = await pipeline.get_tools_for_list("s1")
        tools_s2 = await pipeline.get_tools_for_list("s2")
        assert len(tools_s1) == 2
        assert len(tools_s2) == 1
