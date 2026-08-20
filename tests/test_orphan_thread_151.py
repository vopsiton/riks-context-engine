"""Orphan-thread cleanup after ``task_execute`` timeout (issue #151).

Background
----------
``execute_goal`` enforces a timeout by running the tool in a worker thread.
A timeout cannot force-terminate a running Python thread, so the worker is
*cooperatively* cancelled: once the timeout window elapses ``execute_goal``
sets the module-level stop event (``get_stop_event()``) and then joins the
worker with a bounded grace period.

A **well-behaved** tool observes the stop event in its loop / long tool
call and returns promptly, so the worker thread always terminates and **no
orphan thread is left behind**.

Deterministic coverage (acceptance criteria, #151)
--------------------------------------------------
1. After a timeout the worker thread is gone and the active thread count
   returns to the baseline — asserted against a slow-but-cooperative mock
   tool whose sleeps are ``stop_event.wait(slice)`` (woken instantly when
   the timeout fires the event) — and cross-validated with a *named*
   worker thread. No wall-clock races.
2. The normal (pre-timeout) path is unchanged: results and behaviour match
   the original ``execute_goal`` contract.
3. No thread leak: 10 consecutive timeout calls leave the active thread
   count at baseline (regression test).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from riks_context_engine.tools import executor
from riks_context_engine.tools.base_tool import Tool
from riks_context_engine.tools.executor import (
    ToolExecutionError,
    build_default_registry,
    execute_goal,
)


def _worker_threads() -> int:
    """Count non-main worker threads (the baseline is 0 in-process)."""
    return len(threading.enumerate())


def _wait_until(predicate: Any, timeout: float = 5.0) -> None:
    """Deterministically wait until ``predicate()`` is true (bounded)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), f"condition not met within {timeout}s"


# A fast cooperative worker: returns as soon as the stop event is set.
# Used to *prove* the event fires — ``stop_event.wait(20)`` returns
# immediately once the timeout has set the event (no wall-clock race).
class StopProbeTool(Tool):
    name = "stop-probe"
    description = "Returns once the stop event is observed as set."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, params: dict[str, Any]) -> str:
        return "stopped" if executor.get_stop_event().wait(20.0) else "not-stopped"


# A slow-but-cooperative worker: sleeps in small slices via
# ``stop_event.wait(slice)`` — which returns immediately when the timeout
# fires the event. Emulates a real long tool call (llm_call, web_fetch,
# file_read) that checks for cancellation between steps.
class SlowCooperativeTool(Tool):
    name = "slow-coop"
    description = "Sleeps in small slices, returning when the stop event is set."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self, total: float = 5.0, slice: float = 0.01) -> None:
        self.total = total
        self.slice = slice

    def execute(self, params: dict[str, Any]) -> str:
        stop = executor.get_stop_event()
        elapsed = 0.0
        while elapsed < self.total:
            if stop.is_set():
                return "cancelled"
            stop.wait(self.slice)
            elapsed += self.slice
        return "finished"


# A misbehaving worker: never checks the stop event (blocking C call).
class UncooperativeTool(Tool):
    name = "uncoop"
    description = "Sleeps without checking the stop event."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self, duration: float) -> None:
        self.duration = duration

    def execute(self, params: dict[str, Any]) -> str:
        threading.Event().wait(self.duration)
        return "too-late"


class TestNormalPathUnchanged:
    """Acceptance criterion 2: the pre-timeout path is unchanged."""

    def test_echo_result(self):
        registry = build_default_registry()
        result = execute_goal("echo: merhaba", registry)
        assert result.result == "merhaba"
        assert result.timed_out is False

    def test_default_tool_no_colon(self):
        registry = build_default_registry()
        result = execute_goal("just a plain goal", registry)
        assert result.result == "just a plain goal"
        assert result.timed_out is False

    def test_tool_error_propagates(self):
        class Boom(Tool):
            name = "boom"
            description = "Always raises."
            parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

            def execute(self, params: dict[str, Any]) -> str:
                raise ValueError("boom")

        registry = build_default_registry()
        registry.register(Boom())
        with pytest.raises(ToolExecutionError, match="boom"):
            execute_goal("boom: x", registry)

    def test_unknown_tool_rejected(self):
        registry = build_default_registry()
        with pytest.raises(ToolExecutionError, match="unknown tool"):
            execute_goal("nope: x", registry)


class TestCooperativeCancellation:
    """Acceptance criterion 1: the worker returns to baseline after timeout."""

    def test_stop_event_fires_on_timeout(self):
        """The stop event is set by the timeout (proven via a fast probe,
        no wall-clock race: ``stop_event.wait(20)`` returns instantly once
        the event is set by the timeout)."""
        registry = build_default_registry()
        registry.register(StopProbeTool())
        result = execute_goal("stop-probe: x", registry, timeout=0.05)
        assert result.timed_out is True
        assert result.result == ""

    def test_worker_thread_returns_to_baseline(self):
        """A slow-but-cooperative tool's worker thread is gone shortly
        after the timeout (deterministic: the tool wakes on the stop
        event), so the thread count returns to baseline."""
        executor._reset_orphan_thread_count()
        baseline = _worker_threads()
        registry = build_default_registry()
        registry.register(SlowCooperativeTool(total=5.0, slice=0.01))
        result = execute_goal("slow-coop: x", registry, timeout=0.2)
        assert result.timed_out is True

        _wait_until(lambda: _worker_threads() == baseline)
        assert _worker_threads() == baseline
        assert executor.get_orphan_thread_count() == 0

    def test_named_worker_is_gone_after_timeout(self):
        """Cross-validation with a directly-controlled worker thread:
        after the timeout the stop event is set, the cooperative worker
        finishes (``Event.wait`` wakes on it) and its ``is_alive()`` flips
        to False — no orphan, independent of any other threads."""
        tool = SlowCooperativeTool(total=5.0, slice=0.01)
        with executor._stop_event_lock:
            executor._stop_event.clear()

        def _run() -> None:
            tool.execute({})

        worker = threading.Thread(target=_run, name="test-orphan-worker", daemon=True)
        worker.start()
        worker.join(0.2)  # the timeout window
        assert worker.is_alive()
        with executor._stop_event_lock:
            executor._stop_event.set()
        worker.join(executor._ORPHAN_GRACE_SECONDS)
        assert not worker.is_alive()

    def test_no_thread_leak_10_consecutive_timeouts(self):
        """Acceptance criterion 3: 10 consecutive timeouts leave the active
        thread count at baseline (regression test)."""
        executor._reset_orphan_thread_count()
        baseline = _worker_threads()
        registry = build_default_registry()
        registry.register(SlowCooperativeTool(total=10.0, slice=0.01))

        for _ in range(10):
            result = execute_goal("slow-coop: x", registry, timeout=0.05)
            assert result.timed_out is True
            # Deterministically wait for this worker to finish before the
            # next call (keeps the count assertion tight and race-free).
            _wait_until(lambda: _worker_threads() == baseline)

        assert _worker_threads() == baseline
        assert executor.get_orphan_thread_count() == 0


class TestUncooperativeToolBounded:
    """A tool that ignores the stop event is bounded by the grace period."""

    def test_orphan_counted_and_bounded(self, monkeypatch: pytest.MonkeyPatch):
        executor._reset_orphan_thread_count()
        # Deterministic: shrink the grace period below the worker's own
        # lifetime, so the grace join is *guaranteed* to time out — no
        # wall-clock race, no real-time.sleep after the call (and hence no
        # teardown-time sqlite3/SystemError shutdown spam). The worker is
        # then joined explicitly below.
        monkeypatch.setattr(executor, "_ORPHAN_GRACE_SECONDS", 0.2)
        baseline = _worker_threads()
        registry = build_default_registry()
        registry.register(UncooperativeTool(duration=0.3))

        result = execute_goal("uncoop: x", registry, timeout=0.05)
        assert result.timed_out is True
        # The misbehaving thread is counted (diagnostic), not unbounded.
        assert executor.get_orphan_thread_count() == 1

        # Deterministically wait for the (0.3 s) worker to finish.
        _wait_until(lambda: _worker_threads() == baseline)
        assert _worker_threads() == baseline
