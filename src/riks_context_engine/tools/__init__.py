"""Task execution tools for ``riks task <goal> --execute`` (#137).

Task model (documented here + docs/kullanim-kilavuzu.md):

- **Task** = a goal (string) + optional context (dict). When executed, the
  goal is dispatched to a **tool** in the registry (``<name>: <text>``).
- **Lifecycle states:** ``queued -> running -> done | failed | timeout``.
  Stored by the existing tenant-scoped JSON ``TaskQueue``.
- **Ownership / tenant scoping:** a task belongs to the ``RIKS_TENANT_ID``
  tenant; execution stays in that tenant's scope (a different tenant cannot
  execute it).
- **Execution strategy:** sync by default (``--execute`` blocks and prints
  the result). ``--background`` is a follow-up (job queue + ``--status``).
"""

from __future__ import annotations

from .base_tool import Tool, ToolRegistry
from .echo_tool import EchoTool
from .executor import (
    ExecutionResult,
    ToolExecutionError,
    build_default_registry,
    execute_goal,
    parse_goal,
)

__all__ = [
    "EchoTool",
    "ExecutionResult",
    "Tool",
    "ToolExecutionError",
    "ToolRegistry",
    "build_default_registry",
    "execute_goal",
    "parse_goal",
]
