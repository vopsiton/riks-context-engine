"""Minimal JSON-RPC 2.0 protocol layer for MCP stdio transport."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# JSON-RPC error codes matching the spec
ERR_PARSE_ERROR = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    """A JSON-RPC error with code and message."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


def parse_request(data: str | bytes) -> dict[str, Any]:
    """Parse a raw JSON-RPC 2.0 request/notification."""
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        raise JsonRpcError(ERR_PARSE_ERROR, f"Invalid JSON: {exc}")

    if not isinstance(obj, dict):
        raise JsonRpcError(ERR_INVALID_REQUEST, "Request must be a JSON object")
    if "jsonrpc" not in obj:
        raise JsonRpcError(ERR_INVALID_REQUEST, "Missing jsonrpc field")
    if obj.get("jsonrpc") != "2.0":
        raise JsonRpcError(ERR_INVALID_REQUEST, "Only JSON-RPC 2.0 supported")

    return obj


def build_response(id: Any, result: Any) -> str:
    """Build a successful JSON-RPC response."""
    return json.dumps({"jsonrpc": "2.0", "id": id, "result": result})


def build_error_response(id: Any, code: int, message: str, data: Any = None) -> str:
    """Build a JSON-RPC error response."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": id, "error": err})
