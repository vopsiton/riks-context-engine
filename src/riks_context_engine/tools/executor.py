"""Task execution engine (#137): tool dispatch + sync/timeout execution.

A *task* is a goal (string) that, when executed, is dispatched to a *tool*
(see ``base_tool`` / ``echo_tool``). This module provides:

- :func:`parse_goal` — split a goal string into ``(tool_name, params)``.
- :func:`execute_goal` — dispatch a goal to its tool with an optional
  timeout (sync). Returns ``(result, timed_out)``.

Execution runs in a worker thread so a hard timeout can be enforced. A
goal that is not a string (or a tool that raises) propagates as
``ToolExecutionError``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from riks_context_engine.tools.base_tool import ToolRegistry
from riks_context_engine.tools.echo_tool import EchoTool


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
    """
    try:
        name, params = parse_goal(goal, registry)
    except KeyError as exc:
        raise ToolExecutionError(str(exc)) from exc

    tool = registry.get(name)

    holder: dict[str, Any] = {}

    def _run() -> None:
        try:
            holder["result"] = tool.execute(params)
        except Exception as exc:  # propagate to the caller
            holder["error"] = exc

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        # Timeout: the tool has not returned within the window.
        return ExecutionResult(result="", timed_out=True)

    if "error" in holder:
        raise ToolExecutionError(str(holder["error"]))
    return ExecutionResult(result=str(holder.get("result", "")), timed_out=False)
