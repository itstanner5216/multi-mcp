"""
Tests for Background Task Management (Task 6f):
- Background tasks are tracked in _bg_tasks
- Shutdown cancels all background tasks
- Task done callback removes from tracking list
- Crashed tasks don't take down the server
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.multimcp.multi_mcp import MultiMCP


# ---------------------------------------------------------------------------
# TestTaskTracking
# ---------------------------------------------------------------------------

class TestTaskTracking:
    """Tests that _track_task correctly adds tasks to _bg_tasks."""

    @pytest.mark.asyncio
    async def test_track_task_adds_to_bg_tasks(self):
        """_track_task adds the created task to _bg_tasks."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def long_running():
            await asyncio.sleep(100)

        task = app._track_task(long_running(), "test-task")
        assert task in app._bg_tasks

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_task_done_removes_from_bg_tasks(self):
        """After a task completes normally, it is removed from _bg_tasks."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def quick():
            return "done"

        task = app._track_task(quick(), "quick-task")
        # Wait for the task to complete and callbacks to fire
        await asyncio.sleep(0.05)

        assert task not in app._bg_tasks

    @pytest.mark.asyncio
    async def test_crashed_task_removed_from_bg_tasks(self):
        """After a task raises an exception, it is removed from _bg_tasks."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def crashing():
            raise RuntimeError("boom")

        task = app._track_task(crashing(), "crashing-task")
        # Allow the task to run and done callbacks to fire
        await asyncio.sleep(0.05)

        assert task not in app._bg_tasks

    @pytest.mark.asyncio
    async def test_multiple_tasks_tracked(self):
        """All tracked tasks appear in _bg_tasks simultaneously."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def long_running():
            await asyncio.sleep(100)

        tasks = [
            app._track_task(long_running(), f"task-{i}")
            for i in range(3)
        ]

        assert len(app._bg_tasks) == 3
        for t in tasks:
            assert t in app._bg_tasks

        # Cleanup
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# TestTaskShutdown
# ---------------------------------------------------------------------------

class TestTaskShutdown:
    """Tests that all background tasks are cancelled and cleaned up on shutdown."""

    @pytest.mark.asyncio
    async def test_cancel_all_bg_tasks_on_shutdown(self):
        """Cancelling all tasks in _bg_tasks causes them to be cancelled."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def long_running():
            await asyncio.sleep(100)

        tasks = [
            app._track_task(long_running(), f"shutdown-task-{i}")
            for i in range(2)
        ]

        # Simulate graceful shutdown (mirrors the finally block in run())
        for task in list(app._bg_tasks):
            task.cancel()
        await asyncio.gather(*list(tasks), return_exceptions=True)

        # All tasks should be cancelled
        for t in tasks:
            assert t.cancelled()

    @pytest.mark.asyncio
    async def test_cancelled_tasks_cleaned_from_bg_tasks(self):
        """After cancellation and gather, _bg_tasks is empty (done callbacks fire)."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def long_running():
            await asyncio.sleep(100)

        for i in range(2):
            app._track_task(long_running(), f"cleanup-task-{i}")

        assert len(app._bg_tasks) == 2

        # Simulate graceful shutdown
        for task in list(app._bg_tasks):
            task.cancel()
        await asyncio.gather(*list(app._bg_tasks), return_exceptions=True)

        # Allow done callbacks to propagate
        await asyncio.sleep(0.05)

        assert len(app._bg_tasks) == 0

    @pytest.mark.asyncio
    async def test_shutdown_with_no_bg_tasks_is_safe(self):
        """Shutdown with an empty _bg_tasks list should not raise."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)
        assert app._bg_tasks == []

        # Mimics the finally block in run()
        for task in list(app._bg_tasks):
            task.cancel()
        await asyncio.gather(*list(app._bg_tasks), return_exceptions=True)
        # No exception raised


# ---------------------------------------------------------------------------
# TestTaskCrashIsolation
# ---------------------------------------------------------------------------

class TestTaskCrashIsolation:
    """Tests that a crashing background task does not propagate errors to callers."""

    @pytest.mark.asyncio
    async def test_crashed_bg_task_logs_error_not_raises(self):
        """An exception in a background task is logged, not raised to the caller."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def boom():
            raise ValueError("intentional failure")

        task = app._track_task(boom(), "boom-task")

        # Gathering with return_exceptions=True should not raise
        results = await asyncio.gather(task, return_exceptions=True)
        assert len(results) == 1
        assert isinstance(results[0], ValueError)

        # Task is cleaned from _bg_tasks
        await asyncio.sleep(0.05)
        assert task not in app._bg_tasks

    @pytest.mark.asyncio
    async def test_other_tasks_unaffected_by_one_crash(self):
        """A crashing task does not prevent other tasks from running or being cleaned up."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)
        completed = []

        async def crash():
            raise RuntimeError("crash!")

        async def succeed():
            completed.append("done")

        crash_task = app._track_task(crash(), "crash-task")
        succeed_task = app._track_task(succeed(), "succeed-task")

        # Wait for both to finish
        await asyncio.gather(crash_task, succeed_task, return_exceptions=True)
        await asyncio.sleep(0.05)

        # The non-crashing task completed normally
        assert "done" in completed

        # Both tasks removed from _bg_tasks
        assert crash_task not in app._bg_tasks
        assert succeed_task not in app._bg_tasks

    @pytest.mark.asyncio
    async def test_on_task_done_callback_removes_task(self):
        """_on_task_done is called by asyncio and removes the task from _bg_tasks."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def noop():
            pass

        task = app._track_task(noop(), "noop")
        await asyncio.sleep(0.05)

        # The done callback should have removed the task
        assert task not in app._bg_tasks

    @pytest.mark.asyncio
    async def test_on_task_done_removes_cancelled_task(self):
        """Cancellation also triggers _on_task_done which removes from _bg_tasks."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def forever():
            await asyncio.sleep(1000)

        task = app._track_task(forever(), "forever")
        assert task in app._bg_tasks

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        await asyncio.sleep(0.05)
        assert task not in app._bg_tasks

    @pytest.mark.asyncio
    async def test_multiple_crashes_all_cleaned_up(self):
        """Multiple crashing tasks are all removed from _bg_tasks."""
        app = MultiMCP(transport="sse", host="127.0.0.1", port=18093)

        async def crash(msg):
            raise RuntimeError(msg)

        tasks = [
            app._track_task(crash(f"error-{i}"), f"crash-{i}")
            for i in range(4)
        ]

        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0.05)

        assert len(app._bg_tasks) == 0
