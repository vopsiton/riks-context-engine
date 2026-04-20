"""JSON Schema definitions for MCP tools — cross-model compatible."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tool schemas — each tool's inputSchema as raw JSON Schema draft-07
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = {
    "episodic_search": {
        "name": "episodic_search",
        "description": "Search episodic memory for recent observations and session facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query"],
        },
    },
    "semantic_query": {
        "name": "semantic_query",
        "description": "Query semantic (long-term) memory by subject and predicate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Subject to search for (optional)",
                },
                "predicate": {
                    "type": "string",
                    "description": "Predicate/relation to search for (optional)",
                },
                "query": {
                    "type": "string",
                    "description": "Free-text query (optional, uses semantic search)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
    },
    "procedural_get": {
        "name": "procedural_get",
        "description": "Get procedural memory entries by tag or ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Tag to filter by",
                },
                "entry_id": {
                    "type": "string",
                    "description": "Specific entry ID (optional)",
                },
            },
        },
    },
    "memory_export": {
        "name": "memory_export",
        "description": "Export memory tiers as JSON or YAML for portability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["json", "yaml"],
                    "description": "Export format",
                    "default": "json",
                },
                "tiers": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "procedural"],
                    },
                    "description": "Which tiers to export (all if omitted)",
                },
            },
        },
    },
    "context_add_message": {
        "name": "context_add_message",
        "description": "Add a message to the active context window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["user", "assistant", "system"],
                    "description": "Message role",
                },
                "content": {
                    "type": "string",
                    "description": "Message content",
                },
                "importance": {
                    "type": "number",
                    "description": "Importance 0.0-1.0 (default 0.5)",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "is_grounding": {
                    "type": "boolean",
                    "description": "Mark as grounding (user preferences, active projects)",
                    "default": False,
                },
            },
            "required": ["role", "content"],
        },
    },
    "context_get_summary": {
        "name": "context_get_summary",
        "description": "Get current context window statistics and token usage.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "health_check": {
        "name": "health_check",
        "description": "Check if the MCP server is healthy and responsive.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
}


def get_tool_schema(name: str) -> dict | None:
    """Return the schema dict for a named tool, or None if not found."""
    return TOOL_SCHEMAS.get(name)


def list_tools() -> list[dict]:
    """Return all tool definitions in MCP format."""
    tools = []
    for tool_schema in TOOL_SCHEMAS.values():
        tools.append(
            {
                "name": tool_schema["name"],
                "description": tool_schema["description"],
                "inputSchema": tool_schema["inputSchema"],
            }
        )
    return tools
