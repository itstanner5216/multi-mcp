"""Tests for background task tracking in MultiMCP."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.multimcp.multi_mcp import MultiMCP


@pytest.fixture
def multi_mcp():
    """Create a MultiMCP instance with minimal config."""
    mcp = MultiMCP.__new__(MultiMCP)
    mcp._bg_tasks = set()
    mcp.logger = MagicMock()
    return mcp


class TestTrackTask:
    @pytest.mark.asyncio
    async def test_task_added_to_set(self, multi_mcp):
        async def noop():
            pass

        task = multi_mcp._track_task(noop(), name="test-task")
        assert task in multi_mcp._bg_tasks
        await task

    @pytest.mark.asyncio
    async def test_task_removed_on_completion(self, multi_mcp):
        async def noop():
            pass

        task = multi_mcp._track_task(noop(), name="cleanup-test")
        await task
        # Allow event loop to process done callback
        await asyncio.sleep(0)
        assert task not in multi_mcp._bg_tasks

    @pytest.mark.asyncio
    async def test_failed_task_removed_and_logged(self, multi_mcp):
        async def fail():
            raise ValueError("boom")

        task = multi_mcp._track_task(fail(), name="failing-task")
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)
        assert task not in multi_mcp._bg_tasks
        multi_mcp.logger.error.assert_called_once()
        assert "failing-task" in str(multi_mcp.logger.error.call_args)

    @pytest.mark.asyncio
    async def test_cancelled_task_removed_no_error_log(self, multi_mcp):
        async def hang():
            await asyncio.sleep(999)

        task = multi_mcp._track_task(hang(), name="cancel-test")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert task not in multi_mcp._bg_tasks
        multi_mcp.logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_tasks_tracked_independently(self, multi_mcp):
        async def quick():
            return "done"

        async def slow():
            await asyncio.sleep(0.05)
            return "done"

        t1 = multi_mcp._track_task(quick(), name="fast")
        t2 = multi_mcp._track_task(slow(), name="slow")
        assert len(multi_mcp._bg_tasks) == 2

        await t1
        await asyncio.sleep(0)
        assert t1 not in multi_mcp._bg_tasks
        assert t2 in multi_mcp._bg_tasks

        await t2
        await asyncio.sleep(0)
        assert len(multi_mcp._bg_tasks) == 0
