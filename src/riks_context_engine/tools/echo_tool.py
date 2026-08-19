"""Echo tool — the first (minimal) tool in the task execution engine (#137).

``riks task "echo: merhaba" --execute`` -> prints ``merhaba``.

This validates the execution mechanism (goal -> tool dispatch -> result)
without any external dependency. Follow-up tools: ``llm_call``,
``web_fetch``, ``file_read``.
"""

from __future__ import annotations

from typing import Any

from riks_context_engine.tools.base_tool import Tool


class EchoTool(Tool):
    """Echo back the provided ``text``."""

    name = "echo"
    description = "Echo the provided text back (minimal execution validation)."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo back"},
        },
        "required": ["text"],
    }

    def execute(self, params: dict[str, Any]) -> str:
        text = params.get("text", "")
        if not isinstance(text, str):
            raise TypeError(f"echo: 'text' must be a string, got {type(text).__name__}")
        return text
