# MCP Server Integration — Feature Specification

**Issue:** #34  
**Status:** SPEC — Implementation Pending  
**Priority:** P1  
**Created:** 2026-04-19

---

## 1. Overview

### What Is This?

Expose `riks-context-engine` as a **Model Context Protocol (MCP) server** so AI agents can connect via stdio and query/modify memory tiers using a standardized tool interface.

### Why MCP?

MCP is becoming the de-facto standard for agent-to-tool communication in 2026. Without this integration, riks-context-engine is an isolated component — AI agents have no standard way to connect to it. MCP support makes it a first-class citizen in the agent ecosystem.

### Scope

This spec covers:
- MCP server implementation using `mcp-server-python` or raw stdio
- Memory query tools (episodic, semantic, procedural)
- Context write tools (add message, store memory)
- Tool schema definitions (cross-model compatible)

---

## 2. Architecture

### High-Level Diagram

```
┌──────────────────┐      stdio       ┌─────────────────────────┐
│  AI Agent        │ ◄──────────────► │  riks-context-engine    │
│  (Claude/GPT/    │   MCP protocol   │  MCP Server             │
│   Gemini, etc.)  │                  │  ─────────────────────  │
└──────────────────┘                  │  • episodic_search      │
                                      │  • semantic_query      │
                                      │  • procedural_get      │
                                      │  • add_message         │
                                      │  • store_memory        │
                                      └─────────────────────────┘
```

### Module Structure

```
src/riks_context_engine/
├── mcp/
│   ├── __init__.py
│   ├── server.py          # MCP server entry point
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── memory.py      # Memory tier tools
│   │   └── context.py     # Context window tools
│   └── schemas.py         # JSON Schema definitions for tools
```

---

## 3. Transport

### Stdio (Required)

MCP servers communicate over stdio using JSON-RPC 2.0 messages.

**Server invocation:**
```bash
python -m riks_context_engine.mcp.server
```

**Protocol:** JSON-RPC 2.0 over stdin/stdout
- Inbound: method calls from client
- Outbound: responses and notifications

### Initialization Handshake

On startup, server sends `initialize` response with capabilities:

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "tools": {}
    },
    "serverInfo": {
      "name": "riks-context-engine",
      "version": "0.2.0"
    }
  }
}
```

---

## 4. Tool Definitions

All tools return JSON with schema defined via `inputSchema`.

### 4.1 Memory Tools

#### `episodic_search`
Search episodic (session) memory.

```json
{
  "name": "episodic_search",
  "description": "Search episodic memory for recent observations and session facts",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Search query string"
      },
      "limit": {
        "type": "integer",
        "description": "Max results (default 10)",
        "default": 10
      }
    },
    "required": ["query"]
  }
}
```

**Response:**
```json
{
  "entries": [
    {
      "id": "ep_1234567890",
      "content": "User asked about deployment...",
      "importance": 0.7,
      "timestamp": "2026-04-19T10:30:00Z"
    }
  ]
}
```

#### `semantic_query`
Query long-term structured knowledge.

```json
{
  "name": "semantic_query",
  "description": "Query semantic (long-term) memory by subject and predicate",
  "inputSchema": {
    "type": "object",
    "properties": {
      "subject": {
        "type": "string",
        "description": "Subject to search for (optional)"
      },
      "predicate": {
        "type": "string",
        "description": "Predicate/relation to search for (optional)"
      },
      "limit": {
        "type": "integer",
        "description": "Max results (default 10)",
        "default": 10
      }
    }
  }
}
```

#### `procedural_get`
Retrieve skills, workflows, how-to knowledge.

```json
{
  "name": "procedural_get",
  "description": "Get procedural memory entries by tag or ID",
  "inputSchema": {
    "type": "object",
    "properties": {
      "tag": {
        "type": "string",
        "description": "Tag to filter by"
      },
      "entry_id": {
        "type": "string",
        "description": "Specific entry ID (optional)"
      }
    }
  }
}
```

#### `memory_export`
Export all memory tiers as portable JSON/YAML.

```json
{
  "name": "memory_export",
  "description": "Export memory tiers as JSON or YAML for portability",
  "inputSchema": {
    "type": "object",
    "properties": {
      "format": {
        "type": "string",
        "enum": ["json", "yaml"],
        "default": "json"
      },
      "tiers": {
        "type": "array",
        "items": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
        "description": "Which tiers to export (all if omitted)"
      }
    }
  }
}
```

### 4.2 Context Tools

#### `context_add_message`
Add a message to the context window.

```json
{
  "name": "context_add_message",
  "description": "Add a message to the active context window",
  "inputSchema": {
    "type": "object",
    "properties": {
      "role": {
        "type": "string",
        "enum": ["user", "assistant", "system"],
        "description": "Message role"
      },
      "content": {
        "type": "string",
        "description": "Message content"
      },
      "importance": {
        "type": "number",
        "description": "Importance 0.0-1.0 (default 0.5)",
        "default": 0.5
      },
      "is_grounding": {
        "type": "boolean",
        "description": "Mark as grounding (user preferences, active projects)",
        "default": false
      }
    },
    "required": ["role", "content"]
  }
}
```

#### `context_get_summary`
Get current context window statistics.

```json
{
  "name": "context_get_summary",
  "description": "Get current context window statistics and token usage",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

### 4.3 Utility Tools

#### `health_check`
Ping the server to verify it's running.

```json
{
  "name": "health_check",
  "description": "Check if the MCP server is healthy and responsive",
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

---

## 5. Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RIKS_DATA_DIR` | `data` | Root directory for memory storage |
| `RIKS_CONTEXT_STORAGE` | _(none)_ | Path for context window persistence |
| `RIKS_OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint for embeddings |
| `RIKS_LOG_LEVEL` | `INFO` | Logging level |

### CLI Entry Point

```bash
# Start MCP server
python -m riks_context_engine.mcp.server

# With custom data directory
RIKS_DATA_DIR=/opt/riks/data python -m riks_context_engine.mcp.server
```

---

## 6. Dependencies

```python
# pyproject.toml additions
mcp >= 0.9.0  # MCP Python SDK
```

No new runtime dependencies beyond the MCP SDK.

---

## 7. Error Handling

All tool errors return JSON-RPC error responses:

```json
{
  "jsonrpc": "2.0",
  "id": "<request_id>",
  "error": {
    "code": -32603,
    "message": "Episodic memory entry not found: ep_xyz",
    "data": {"entry_id": "ep_xyz"}
  }
}
```

| Code | Meaning |
|------|---------|
| -32600 | Invalid Request |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |

---

## 8. Acceptance Criteria

### AC1: Server Startup
- [ ] `python -m riks_context_engine.mcp.server` starts without errors
- [ ] Server responds to `initialize` handshake with correct capabilities
- [ ] Server responds to `tools/list` with all defined tools

### AC2: Memory Tools
- [ ] `episodic_search` returns matching entries from episodic memory
- [ ] `semantic_query` returns matching entries by subject/predicate
- [ ] `procedural_get` returns entries by tag or ID
- [ ] `memory_export` produces valid JSON/YAML with all requested tiers

### AC3: Context Tools
- [ ] `context_add_message` adds a message and returns confirmation
- [ ] `context_get_summary` returns accurate token counts and message counts

### AC4: Error Handling
- [ ] Invalid tool params return -32602 error
- [ ] Missing required params return descriptive error
- [ ] Server continues running after errors (no crash)

### AC5: Cross-Model Compatibility
- [ ] All tool schemas are valid JSON Schema draft-07
- [ ] Tool descriptions are clear enough for zero-shot tool use by LLMs
- [ ] No model-specific assumptions in schemas (works with Claude, GPT, Gemini)

### AC6: Integration Test
- [ ] Test that MCP server starts, accepts a tool call, and returns valid response

---

## 9. Out of Scope

- HTTP/WebSocket transport (stdio only for v1)
- Authentication/authorization (use process-level isolation)
- Streaming tool responses
- Multi-agent coordination

---

## 10. Reference

- [MCP Protocol Spec](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- JSON-RPC 2.0 Spec: https://www.jsonrpc.org/specification
