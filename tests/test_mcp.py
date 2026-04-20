"""Tests for the MCP server (JSON-RPC 2.0 stdio)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from riks_context_engine.mcp.protocol import (
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    ERR_PARSE_ERROR,
    JsonRpcError,
    build_error_response,
    build_response,
    parse_request,
)
from riks_context_engine.mcp.schemas import TOOL_SCHEMAS, get_tool_schema, list_tools
from riks_context_engine.mcp.server import MCPServer, _format_result

# ---------------------------------------------------------------------------
# Protocol layer
# ---------------------------------------------------------------------------


class TestParseRequest:
    def test_valid_request(self) -> None:
        obj = parse_request('{"jsonrpc": "2.0", "method": "ping", "id": 1}')
        assert obj["method"] == "ping"
        assert obj["id"] == 1

    def test_valid_notification(self) -> None:
        obj = parse_request('{"jsonrpc": "2.0", "method": "ping"}')
        assert obj["method"] == "ping"
        assert "id" not in obj

    def test_invalid_json(self) -> None:
        with pytest.raises(JsonRpcError) as exc_info:
            parse_request("not json")
        assert exc_info.value.code == ERR_PARSE_ERROR

    def test_missing_jsonrpc(self) -> None:
        with pytest.raises(JsonRpcError) as exc_info:
            parse_request('{"method": "ping", "id": 1}')
        assert exc_info.value.code == ERR_INVALID_REQUEST

    def test_wrong_version(self) -> None:
        with pytest.raises(JsonRpcError) as exc_info:
            parse_request('{"jsonrpc": "1.0", "method": "ping", "id": 1}')
        assert exc_info.value.code == ERR_INVALID_REQUEST


class TestBuildResponse:
    def test_success(self) -> None:
        resp = build_response(1, {"status": "ok"})
        obj = json.loads(resp)
        assert obj["jsonrpc"] == "2.0"
        assert obj["id"] == 1
        assert obj["result"]["status"] == "ok"

    def test_null_id(self) -> None:
        resp = build_response(None, None)
        obj = json.loads(resp)
        assert obj["id"] is None
        assert obj["result"] is None


class TestBuildErrorResponse:
    def test_error(self) -> None:
        resp = build_error_response(1, ERR_METHOD_NOT_FOUND, "Method not found")
        obj = json.loads(resp)
        assert obj["error"]["code"] == ERR_METHOD_NOT_FOUND
        assert obj["error"]["message"] == "Method not found"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestToolSchemas:
    def test_all_tools_have_required_fields(self) -> None:
        for name, schema in TOOL_SCHEMAS.items():
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema
            assert schema["inputSchema"]["type"] == "object"

    def test_episodic_search_has_query_required(self) -> None:
        schema = get_tool_schema("episodic_search")
        assert schema is not None
        assert "query" in schema["inputSchema"]["required"]

    def test_context_add_message_has_role_required(self) -> None:
        schema = get_tool_schema("context_add_message")
        assert schema is not None
        assert "role" in schema["inputSchema"]["required"]
        assert "content" in schema["inputSchema"]["required"]

    def test_list_tools_returns_all(self) -> None:
        tools = list_tools()
        names = {t["name"] for t in tools}
        expected = {
            "episodic_search",
            "semantic_query",
            "procedural_get",
            "memory_export",
            "context_add_message",
            "context_get_summary",
            "health_check",
        }
        assert expected.issubset(names)


# ---------------------------------------------------------------------------
# MCPServer unit tests (no I/O)
# ---------------------------------------------------------------------------


class TestMCPServer:
    @pytest.fixture
    def server(self) -> MCPServer:
        return MCPServer(data_dir="/tmp/riks_test_mcp")

    def test_initialize(self, server: MCPServer) -> None:
        result = server.handle_initialize({})
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "riks-context-engine"

    def test_ping(self, server: MCPServer) -> None:
        result = server.handle_ping()
        assert result == {"pong": True}

    def test_tools_list(self, server: MCPServer) -> None:
        result = server.handle_tools_list()
        assert "tools" in result
        assert len(result["tools"]) >= 7

    def test_health_check(self, server: MCPServer) -> None:
        result = server.handler.health_check({})
        assert result["status"] == "ok"
        assert result["version"] == "0.2.0"

    def test_unknown_method(self, server: MCPServer) -> None:
        request = {"jsonrpc": "2.0", "method": "nonexistent", "id": 1}
        response = server.dispatch(request)
        assert response is not None
        obj = json.loads(response)
        assert obj["error"]["code"] == ERR_METHOD_NOT_FOUND

    def test_dispatch_notification_no_response(self, server: MCPServer) -> None:
        # Notifications have no id — should return None (no stdout write)
        request = {"jsonrpc": "2.0", "method": "ping"}
        assert server.dispatch(request) is None

    def test_episodic_search_empty(self, server: MCPServer) -> None:
        result = server.handle_tools_call(
            {"name": "episodic_search", "arguments": {"query": "test", "limit": 5}}
        )
        assert "content" in result
        assert result["content"][0]["type"] == "text"

    def test_context_add_message(self, server: MCPServer) -> None:
        result = server.handle_tools_call(
            {
                "name": "context_add_message",
                "arguments": {"role": "user", "content": "Hello world"},
            }
        )
        assert "content" in result
        text = result["content"][0]["text"]
        assert "message_id" in text
        assert "added" in text

    def test_context_get_summary(self, server: MCPServer) -> None:
        result = server.handle_tools_call({"name": "context_get_summary", "arguments": {}})
        assert "content" in result
        text = result["content"][0]["text"]
        # Should contain token stats
        parsed = json.loads(text)
        assert "current_tokens" in parsed
        assert "max_tokens" in parsed

    def test_missing_required_param(self, server: MCPServer) -> None:
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": "episodic_search", "arguments": {}},
        }
        response = server.dispatch(request)
        obj = json.loads(response)
        assert obj["error"]["code"] == -32602  # Invalid params

    def test_unknown_tool(self, server: MCPServer) -> None:
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
        response = server.dispatch(request)
        obj = json.loads(response)
        assert obj["error"]["code"] == ERR_METHOD_NOT_FOUND


class TestFormatResult:
    def test_dict_result(self) -> None:
        result = _format_result("health_check", {"status": "ok"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"


# ---------------------------------------------------------------------------
# Integration tests (subprocess stdio)
# ---------------------------------------------------------------------------


class TestMCPIntegration:
    """Run the actual server subprocess and send JSON-RPC messages."""

    @pytest.fixture
    def server_process(self, tmp_path: Any) -> subprocess.Popen:
        venv_python = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"
        python_bin = str(venv_python) if venv_python.exists() else sys.executable
        repo_root = Path(__file__).resolve().parents[1]
        env = {
            "RIKS_DATA_DIR": str(tmp_path / "data"),
            "RIKS_LOG_LEVEL": "ERROR",
            "PYTHONPATH": str(repo_root / "src"),
        }
        proc = subprocess.Popen(
            [python_bin, "-m", "riks_context_engine.mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(repo_root),
            env=env,
            text=True,
        )
        yield proc
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait(timeout=5)

    def _send(self, proc: subprocess.Popen, request: dict[str, Any]) -> dict[str, Any] | None:
        line = json.dumps(request) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()
        resp_line = proc.stdout.readline()
        if not resp_line:
            return None
        return json.loads(resp_line.strip())

    def test_initialize_handshake(self, server_process: subprocess.Popen) -> None:
        resp = self._send(
            server_process,
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "clientInfo": {}},
            },
        )
        assert resp is not None
        assert resp["id"] == 0
        assert "protocolVersion" in resp["result"]

    def test_tools_list_after_init(self, server_process: subprocess.Popen) -> None:
        # Initialise first
        self._send(
            server_process,
            {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}},
        )
        resp = self._send(
            server_process, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        assert resp is not None
        assert len(resp["result"]["tools"]) >= 7

    def test_health_check_tool(self, server_process: subprocess.Popen) -> None:
        self._send(
            server_process,
            {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}},
        )
        resp = self._send(
            server_process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "health_check", "arguments": {}},
            },
        )
        assert resp is not None
        assert resp["id"] == 2
        assert "ok" in resp["result"]["content"][0]["text"]

    def test_context_add_and_summary(self, server_process: subprocess.Popen) -> None:
        self._send(
            server_process,
            {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}},
        )
        # Add a message
        add_resp = self._send(
            server_process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "context_add_message",
                    "arguments": {"role": "user", "content": "test message"},
                },
            },
        )
        assert add_resp is not None
        assert add_resp["id"] == 3

        # Get summary
        summary_resp = self._send(
            server_process,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "context_get_summary", "arguments": {}},
            },
        )
        assert summary_resp is not None
        assert summary_resp["id"] == 4
        text = summary_resp["result"]["content"][0]["text"]
        parsed = json.loads(text)
        assert parsed["messages_count"] >= 1

    def test_invalid_jsonrpc_version(self, server_process: subprocess.Popen) -> None:
        # When jsonrpc version is wrong, parse_request raises - but we still
        # need a response. The server sends an error with id=null.
        server_process.stdin.write('{"jsonrpc": "1.0", "method": "ping", "id": 99}\n')
        server_process.stdin.flush()
        resp_line = server_process.stdout.readline()
        assert resp_line
        resp = json.loads(resp_line)
        assert "error" in resp
        assert resp["id"] == 99
