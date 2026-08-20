"""Task execution engine (#137): tool dispatch + sync/timeout execution.

A *task* is a goal (string) that, when executed, is dispatched to a *tool*
(see ``base_tool`` / ``echo_tool``). This module provides:

- :func:`parse_goal` — split a goal string into ``(tool_name, params)``.
- :func:`execute_goal` — dispatch a goal to its tool with an optional
  timeout (sync). Returns ``(result, timed_out)``.

Execution runs in a worker thread so a hard timeout can be enforced. A
goal that is not a string (or a tool that raises) propagates as
``ToolExecutionError``.

Timeout semantics (orphan-thread cleanup, #151):

A timeout *cannot* force-terminate a running Python thread (there is no
safe ``Thread.kill``); ``concurrent.futures.Future.cancel()`` would not
stop a worker that is already running either. Instead ``execute_goal``
uses **cooperative cancellation**: it sets a module-level
``threading.Event`` (``get_stop_event``) once the timeout window elapses
and then waits for the worker to finish with a bounded
``join(_ORPHAN_GRACE_SECONDS)``.

Well-behaved tools (and any loop / long tool call that periodically
consults the stop event) see ``stop_event.is_set()`` and return
promptly, so the worker thread always terminates and **no orphan thread
is left behind**. Tools that ignore the event (e.g. a blocking C call)
are joined for a short grace period (``_ORPHAN_GRACE_SECONDS``) only;
if the thread is still alive it is logged and counted by
``get_orphan_thread_count()`` — a bounded diagnostic, not an unbounded
leak. See ``tests/test_orphan_thread_151.py`` for the deterministic
coverage (baseline restore, no-leak regression, normal-path
invariance).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from riks_context_engine.tools.base_tool import ToolRegistry
from riks_context_engine.tools.echo_tool import EchoTool

logger = logging.getLogger(__name__)

# How long (seconds) to join a still-running worker thread after its
# timeout window elapses, before giving up and logging it as an orphan.
# Bounded: a misbehaving tool cannot block the caller indefinitely. Kept
# short so an uncooperative tool cannot delay the caller by the full grace
# period (the MCP server, for example, promises a sub-2 s response).
_ORPHAN_GRACE_SECONDS = 0.5

# Cooperative cancellation state, shared with worker threads.
_stop_event = threading.Event()
_stop_event_lock = threading.Lock()
_orphan_thread_count = 0


def get_stop_event() -> threading.Event:
    """Return the cooperative-cancellation event.

    Tools and worker loops may consult ``is_set()`` periodically to stop
    early when a timeout fires (see module docstring). A fresh, cleared
    event is returned on every :func:`execute_goal` call.
    """
    return _stop_event


def get_orphan_thread_count() -> int:
    """Return the number of worker threads that outlived their join grace
    period (a diagnostic counter, see module docstring)."""
    return _orphan_thread_count


def _reset_orphan_thread_count() -> None:
    """Test helper: reset the orphan counter to zero."""
    global _orphan_thread_count
    _orphan_thread_count = 0


class ToolExecutionError(Exception):
    """Raised when a tool fails to execute (bad goal, unknown tool, tool error)."""


def build_default_registry() -> ToolRegistry:
    """Registry seeded with the built-in tools (echo is the default)."""
    registry = ToolRegistry()
    registry.register(EchoTool(), default=True)
    return registry


def parse_goal(goal: str, registry: ToolRegistry) -> tuple[str, dict[str, Any]]:
    """Parse a goal string into ``(tool_name, params)``.

    - ``"echo: merhaba"`` -> ``("echo", {"text": "merhaba"})``
    - ``"merhaba"`` (no ``:``) -> default tool (echo) with the whole string.

    For the ``echo`` tool (and any single-``text``-param tool) the argument
    is mapped to ``text``. Unknown tools with a ``:`` argument raise
    ``ToolExecutionError`` (fail-closed, #137).
    """
    goal = goal.strip()
    if not goal:
        raise ToolExecutionError("empty goal")

    if ":" in goal:
        name, _, arg = goal.partition(":")
        name = name.strip()
        arg = arg.strip()
        if not name:
            raise ToolExecutionError("empty tool name in goal")
        try:
            tool = registry.get(name)
        except KeyError:
            raise ToolExecutionError(f"unknown tool: {name!r}") from None
        return name, _to_params(tool, arg)

    # No tool prefix -> default tool with the whole goal as argument.
    default_name = registry.default_name()
    if default_name is None:
        raise ToolExecutionError("no default tool registered")
    tool = registry.get(default_name)
    return default_name, _to_params(tool, goal)


def _to_params(tool: Any, arg: str) -> dict[str, Any]:
    """Map a raw string argument to a tool's first (``text``) parameter.

    Only the single-string-parameter convention is supported for now
    (echo). This keeps the goal grammar simple: ``<name>: <text>``.
    """
    props = (tool.parameters or {}).get("properties", {})
    # Find the first string-typed property (echo -> "text").
    text_key = next(
        (k for k, v in props.items() if isinstance(v, dict) and v.get("type") == "string"),
        None,
    )
    if text_key is None:
        # Fallback: pass under "text" for echo-style tools.
        text_key = "text"
    return {text_key: arg}


@dataclass
class ExecutionResult:
    """Outcome of a sync goal execution."""

    result: str
    timed_out: bool = False


def execute_goal(
    goal: str,
    registry: ToolRegistry,
    *,
    timeout: float | None = None,
) -> ExecutionResult:
    """Execute a goal (sync) with an optional hard timeout.

    Returns an :class:`ExecutionResult`. Raises ``ToolExecutionError`` on a
    bad goal / unknown tool / tool error. A ``timeout`` (seconds) that
    elapses before the tool returns yields ``timed_out=True``.

    Timeout path (cooperative cancellation, #151): once the window elapses
    the module-level stop event (``get_stop_event()``) is set and the worker
    thread is joined with a short, bounded grace period. Well-behaved tools
    observe the event and return promptly, so no orphan thread is left
    behind; a thread that ignores the event is logged and counted (see
    module docstring and ``tests/test_orphan_thread_151.py``).
    """
    global _orphan_thread_count

    try:
        name, params = parse_goal(goal, registry)
    except KeyError as exc:
        raise ToolExecutionError(str(exc)) from exc

    tool = registry.get(name)

    holder: dict[str, Any] = {}

    # Reset cooperative-cancellation state for this call.
    with _stop_event_lock:
        _stop_event.clear()

    def _run() -> None:
        try:
            holder["result"] = tool.execute(params)
        except Exception as exc:  # propagate to the caller
            holder["error"] = exc

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        # Timeout: the tool has not returned within the window. Signal
        # cooperative cancellation, then wait a bounded grace period for
        # the (well-behaved) tool to observe the event and finish.
        with _stop_event_lock:
            _stop_event.set()
        worker.join(_ORPHAN_GRACE_SECONDS)
        if worker.is_alive():
            # The tool ignored the stop event (e.g. blocking C call).
            # Count it as an orphan for diagnostics; we do not block.
            _orphan_thread_count += 1
            logger.warning(
                "task_execute: worker thread for tool %r outlived its join grace "
                "period after a timeout and may outlive this process (orphan #%d)",
                name,
                _orphan_thread_count,
            )
        return ExecutionResult(result="", timed_out=True)

    if "error" in holder:
        raise ToolExecutionError(str(holder["error"]))
    return ExecutionResult(result=str(holder.get("result", "")), timed_out=False)
