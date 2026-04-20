#!/usr/bin/env python3
"""MCP Server — Model Context Protocol stdio server for riks-context-engine.

Receives JSON-RPC 2.0 requests on stdin, dispatches to the appropriate
tool handler, and writes responses to stdout.

Usage:
    python -m riks_context_engine.mcp.server

Environment:
    RIKS_DATA_DIR   data directory for memory storage (default: data)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from .handlers import create_handler
from .protocol import (
    ERR_INTERNAL_ERROR,
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    JsonRpcError,
    build_error_response,
    build_response,
    parse_request,
)
from .schemas import TOOL_SCHEMAS, list_tools

logger = logging.getLogger(__name__)

# Protocol version as defined in MCP spec
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "riks-context-engine", "version": "0.2.0"}

# Supported JSON-RPC methods
MCP_METHODS = {
    "initialize",
    "initialized",
    "tools/list",
    "tools/call",
    "ping",
    "notifications/initialized",
}


class MCPServer:
    """MCP stdio server — handles JSON-RPC 2.0 over stdin/stdout."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or os.environ.get("RIKS_DATA_DIR", "data")
        self.handler = create_handler(data_dir=self.data_dir)
        self._initialised = False

    # ------------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------------

    def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle JSON-RPC initialize request."""
        client_info = params.get("clientInfo", {})
        logger.debug("initialize from %s", client_info)
        self._initialised = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }

    def handle_ping(self) -> dict[str, Any]:
        """Handle ping — used to check server is alive."""
        return {"pong": True}

    def handle_tools_list(self) -> dict[str, Any]:
        """Handle tools/list — return all available tool definitions."""
        return {"tools": list_tools()}

    def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call — invoke a named tool with given arguments."""
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if not tool_name:
            raise JsonRpcError(ERR_INVALID_REQUEST, "Missing tool name")

        schema = TOOL_SCHEMAS.get(tool_name)
        if not schema:
            raise JsonRpcError(ERR_METHOD_NOT_FOUND, f"Unknown tool: {tool_name}")

        # Validate required params
        input_schema: dict[str, Any] = schema["inputSchema"]  # type: ignore[assignment]
        required = input_schema.get("required", [])
        for req in required:
            if req not in tool_args:
                raise JsonRpcError(
                    ERR_INVALID_PARAMS,
                    f"Missing required parameter: {req}",
                    {"parameter": req},
                )

        # Dispatch to handler method
        handler_method = getattr(self.handler, tool_name, None)
        if not handler_method or not callable(handler_method):
            raise JsonRpcError(
                ERR_METHOD_NOT_FOUND, f"No handler for tool: {tool_name}"
            )

        result = handler_method(tool_args)

        return {
            "content": [
                {
                    "type": "text",
                    "text": _format_result(tool_name, result),
                }
            ]
        }

    # ------------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------------

    def dispatch(self, request: dict[str, Any]) -> str | None:
        """Parse a JSON-RPC request and return the response string (or None)."""
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {})

        # Notifications (no id) are ack'd with None — nothing to send
        is_notification = request_id is None

        try:
            if method == "initialize":
                result = self.handle_initialize(params)
            elif method == "ping":
                result = self.handle_ping()
            elif method == "tools/list":
                result = self.handle_tools_list()
            elif method == "tools/call":
                result = self.handle_tools_call(params)
            elif method in MCP_METHODS or method.startswith("notifications/"):
                # Valid but no-op MCP methods we don't implement
                result = None
            else:
                raise JsonRpcError(
                    ERR_METHOD_NOT_FOUND, f"Unknown method: {method}"
                )

            if is_notification:
                return None

            if result is None:
                # Void result — return null response
                return build_response(request_id, None)

            return build_response(request_id, result)

        except JsonRpcError as exc:
            return build_error_response(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("Unhandled error in dispatch")
            if is_notification:
                return None
            return build_error_response(
                request_id, ERR_INTERNAL_ERROR, f"Internal error: {exc}"
            )


def _format_result(tool_name: str, result: dict[str, Any]) -> str:
    """Format a tool result as a human-readable text block."""
    import json

    try:
        return json.dumps(result, indent=2, default=str)
    except Exception:
        return str(result)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _read_request() -> dict[str, Any] | None:
    """Read one line from stdin, return parsed JSON or None on EOF.

    Returns None on clean EOF. Raises JsonRpcError for parse-level errors
    so the caller can send an error response.
    """
    try:
        line = sys.stdin.readline()
    except EOFError:
        return None

    if not line:
        return None

    # Try to extract id for error reporting even if parse fails
    raw: dict[str, Any] = {}
    try:
        import json
        raw = json.loads(line)
    except Exception:
        pass  # Can't extract id from non-JSON

    req_id = raw.get("id") if isinstance(raw, dict) else None

    try:
        return parse_request(line.strip())
    except JsonRpcError as exc:
        # Re-raise with the id so main() can build an error response
        exc.data = {"_req_id": req_id, "_raw": raw}
        raise


def _write_response(response: str | None) -> None:
    """Write a JSON-RPC response (or blank line for notifications) to stdout."""
    if response is not None:
        sys.stdout.write(response + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP stdio server loop."""
    logging.basicConfig(
        level=os.environ.get("RIKS_LOG_LEVEL", "WARNING"),
        format="%(levelname)s %(name)s: %(message)s",
    )

    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    server = MCPServer(data_dir=data_dir)

    while True:
        try:
            request = _read_request()
        except JsonRpcError as exc:
            # Parse-level error (e.g. invalid JSON or missing jsonrpc field)
            req_id = exc.data.get("_req_id") if exc.data else None
            # If we can't determine the id from the raw JSON, use null
            resp_id: Any = req_id if req_id is not None else None
            _write_response(build_error_response(resp_id, exc.code, exc.message))
            continue

        if request is None:
            break  # EOF — client disconnected

        response = server.dispatch(request)
        _write_response(response)


if __name__ == "__main__":
    main()
