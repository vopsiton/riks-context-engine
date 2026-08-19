"""Base Tool abstraction for the task execution engine (#137).

A *task* is a goal (string) that, when executed, is dispatched to a *tool*.
Each tool declares a ``name``, ``description``, ``parameters`` (JSON schema)
and implements ``execute(params) -> str``.

The goal string is parsed as ``<name>: <args...>`` — e.g. ``echo: merhaba``
dispatches to the ``echo`` tool with ``text="merhaba"``. A goal with no
``:`` is treated as a call to the default tool (``echo``) with the whole
string as the argument.

This is a minimal, dependency-free registry so the execution mechanism can
be validated with the ``echo`` tool; richer tools (``llm_call``,
``web_fetch``, ``file_read``) are follow-ups.
"""

from __future__ import annotations

from typing import Any


class Tool:
    """Abstract tool interface."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    def execute(self, params: dict[str, Any]) -> str:
        raise NotImplementedError


def _default_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
        "required": [],
    }


class ToolRegistry:
    """In-memory registry of :class:`Tool` instances, keyed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._default: str | None = None

    def register(self, tool: Tool, *, default: bool = False) -> None:
        if not tool.name:
            raise ValueError(f"tool {tool!r} has no name")
        self._tools[tool.name] = tool
        if default or self._default is None:
            self._default = tool.name

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"unknown tool: {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def default_name(self) -> str | None:
        return self._default

    def dispatch(self, name: str, params: dict[str, Any]) -> str:
        return self.get(name).execute(params)
