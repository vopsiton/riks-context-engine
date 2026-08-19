"""Tests for task_execute MCP tool (#107).

Covers:
- Echo goal → success
- Unknown tool → -32602
- Empty goal → -32602
- Timeout: slow tool, timeout=1, returns within 2s, no exception
- Post-timeout ping → server alive
- Timeout > 120 → schema rejects with -32602
- Tenant isolation: agentA task not visible to agentB
- Missing/invalid tenant_id → -32602
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from riks_context_engine.mcp.protocol import ERR_INVALID_PARAMS
from riks_context_engine.mcp.server import SERVER_INFO, MCPServer
from riks_context_engine.tools.base_tool import Tool


class SlowTool(Tool):
    """Tool that sleeps for a configurable duration (for timeout tests)."""

    name = "slow"
    description = "Sleeps for N seconds."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    }

    def execute(self, params: dict[str, Any]) -> str:
        time.sleep(10)
        return "done"


@pytest.fixture
def server(tmp_path: Path) -> MCPServer:
    s = MCPServer(data_dir=str(tmp_path / "data"))
    s.handle_initialize({})
    return s


def _call(server: MCPServer, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }
    resp = server.dispatch(request)
    assert resp is not None
    return json.loads(resp)


class TestTaskExecuteSuccess:
    def test_echo_goal(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-test",
                "goal": "echo: merhaba",
            },
        )
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["status"] == "done"
        assert "merhaba" in content["result"]

    def test_default_tool_no_colon(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-test",
                "goal": "plain text goal",
            },
        )
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["status"] == "done"
        assert "plain text goal" in content["result"]


class TestTaskExecuteErrors:
    def test_unknown_tool(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-test",
                "goal": "nonexistent_tool: x",
            },
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS
        assert "unknown tool" in resp["error"]["message"]

    def test_empty_goal(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-test",
                "goal": "",
            },
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS

    def test_missing_tenant_id(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "goal": "echo: hi",
            },
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS

    def test_invalid_tenant_id(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "",
                "goal": "echo: hi",
            },
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS


class TestTaskExecuteTimeout:
    def test_timeout_returns_status_no_exception(self, server: MCPServer) -> None:
        from riks_context_engine.tools.executor import build_default_registry

        registry = build_default_registry()
        registry.register(SlowTool())
        server.handler._tool_registry = registry

        t0 = time.monotonic()
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-timeout",
                "goal": "slow: x",
                "timeout": 1,
            },
        )
        elapsed = time.monotonic() - t0

        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["status"] == "timeout"
        assert content["result"] is None
        assert elapsed < 2.0

    def test_post_timeout_ping(self, server: MCPServer) -> None:
        from riks_context_engine.tools.executor import build_default_registry

        registry = build_default_registry()
        registry.register(SlowTool())
        server.handler._tool_registry = registry

        _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-timeout2",
                "goal": "slow: x",
                "timeout": 1,
            },
        )

        ping_req = {"jsonrpc": "2.0", "id": 99, "method": "ping"}
        ping_resp = json.loads(server.dispatch(ping_req))
        assert ping_resp["result"]["pong"] is True

    def test_timeout_clamped_to_120(self, server: MCPServer) -> None:
        resp = _call(
            server,
            "task_execute",
            {
                "tenant_id": "t-test",
                "goal": "echo: fast",
                "timeout": 9999,
            },
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS


class TestTaskExecuteTenantIsolation:
    def test_tenant_scoped_queue(self, server: MCPServer, tmp_path: Path) -> None:
        _call(
            server,
            "task_execute",
            {
                "tenant_id": "agentA",
                "goal": "echo: secret",
            },
        )

        a_tasks = tmp_path / "data" / "tenants" / "agentA" / "tasks.json"
        assert a_tasks.exists()
        data = json.loads(a_tasks.read_text())
        task = data["tasks"][0]
        assert task["owner_tenant"] == "agentA"
        assert task["status"] == "done"

        b_tasks = tmp_path / "data" / "tenants" / "agentB" / "tasks.json"
        assert not b_tasks.exists()


class TestVersionConsistency:
    def test_server_info_version(self) -> None:
        assert SERVER_INFO["version"] == "0.3.0"

    def test_health_check_matches_server_info(self, server: MCPServer) -> None:
        result = server.handler.health_check({})
        assert result["version"] == SERVER_INFO["version"]

    def test_init_response_version(self, server: MCPServer) -> None:
        resp = server.handle_initialize({})
        assert resp["serverInfo"]["version"] == "0.3.0"


class TestToolsList:
    def test_nine_tools(self, server: MCPServer) -> None:
        result = server.handle_tools_list()
        names = {t["name"] for t in result["tools"]}
        assert len(names) == 9
        assert "task_execute" in names
        assert "semantic_write" in names
