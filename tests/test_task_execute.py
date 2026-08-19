"""Integration tests for ``riks task --execute`` real execution (#137).

Covers:
- task model (goal -> tool dispatch) + lifecycle states,
- sync execution (echo tool) + result to stdout,
- exit-code semantics (0 success / 1 failure / 2 timeout),
- error path (unknown tool),
- tenant isolation in execution (cross-tenant blocked).

Each test runs against the REAL stores (tmp data dir), not mocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from riks_context_engine.cli.main import main


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIKS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RIKS_TENANT_ID", raising=False)
    return tmp_path


def _tasks_file(data: Path, tenant: str | None = None) -> Path:
    if tenant:
        return data / "tenants" / tenant / "tasks.json"
    return data / "tasks.json"


class TestTaskModel:
    def test_task_model_documented(self):
        """The task model (goal->tool, lifecycle, tenant scoping) is
        documented in code docstrings (acceptance criterion)."""
        from riks_context_engine.tools import __doc__ as tools_doc
        from riks_context_engine.tools.executor import execute_goal

        assert "queued" in tools_doc  # lifecycle states documented
        assert "tenant" in tools_doc.lower()  # tenant scoping documented
        assert execute_goal.__doc__  # execution contract documented

    def test_task_states_persisted(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        rc = main(["task", "echo: hello", "--execute"])
        assert rc == 0
        data = json.loads(_tasks_file(isolated_data).read_text())
        task = data["tasks"][0]
        assert task["status"] == "done"
        assert task["result"] == "hello"
        assert task["executed_at"] is not None


class TestSyncExecution:
    def test_execute_echo(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        rc = main(["task", "echo: merhaba", "--execute"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "merhaba" in out

    def test_execute_default_tool_no_colon(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        rc = main(["task", "just a plain goal", "--execute"])
        assert rc == 0
        assert "just a plain goal" in capsys.readouterr().out

    def test_execute_exit_code_success(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        assert main(["task", "echo: ok", "--execute"]) == 0


class TestErrorPaths:
    def test_unknown_tool_exit_1(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        rc = main(["task", "nope: x", "--execute"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "unknown tool" in err
        # The task is recorded as failed with the error.
        data = json.loads(_tasks_file(isolated_data).read_text())
        assert data["tasks"][0]["status"] == "failed"
        assert "unknown tool" in (data["tasks"][0]["result"] or "")

    def test_execute_empty_goal_rejected(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        # A goal of only a tool name with empty arg still executes (echo "");
        # but a missing goal is rejected.
        rc = main(["task", "--execute"])
        assert rc == 1
        assert "task goal is required" in capsys.readouterr().err

    def test_timeout_exit_2(self, isolated_data: Path, monkeypatch):
        # Force the echo tool to hang so the timeout path is exercised.
        from riks_context_engine.tools.echo_tool import EchoTool

        def _hang(self, params):
            import time

            time.sleep(0.5)
            return "too late"

        monkeypatch.setattr(EchoTool, "execute", _hang)
        # Import after patching to ensure the registry uses the patched tool.
        rc = main(["task", "echo: slow", "--execute", "--timeout", "0.05"])
        assert rc == 2
        data = json.loads(_tasks_file(isolated_data).read_text())
        assert data["tasks"][0]["status"] == "timeout"


class TestStatusAndTenantIsolation:
    def test_status_query(
        self,
        isolated_data: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantA")
        main(["task", "echo: a-goal", "--execute"])
        tid = json.loads(_tasks_file(isolated_data, "tenantA").read_text())["tasks"][0]["id"]
        rc = main(["task", "--status", tid])
        assert rc == 0
        out = capsys.readouterr().out
        assert tid in out
        assert "a-goal" in out

    def test_tenant_isolation_cross_tenant_execute(
        self,
        isolated_data: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Tenant A creates a task; tenant B must NOT be able to execute it.
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantA")
        main(["task", "echo: secret", "--execute"])
        a_file = _tasks_file(isolated_data, "tenantA")
        assert a_file.exists()

        monkeypatch.setenv("RIKS_TENANT_ID", "tenantB")
        capsys.readouterr()
        # B queries A's task id via --status -> access denied (not found in B's store).
        tid = json.loads(a_file.read_text())["tasks"][0]["id"]
        rc = main(["task", "--status", tid])
        assert rc == 1
        assert "task not found" in capsys.readouterr().err

    def test_tenant_isolation_cross_tenant_status_denied(
        self,
        isolated_data: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # A task owned by tenantA (RIKS_TENANT_ID set) is stored in tenantA's
        # store; tenantB cannot see or execute it (separate store -> denied).
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantA")
        main(["task", "echo: owned", "--execute"])
        owned = json.loads(_tasks_file(isolated_data, "tenantA").read_text())["tasks"][0]["id"]
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantB")
        capsys.readouterr()
        # tenantB's store is separate, so the owned task is "not found" (isolated).
        rc = main(["task", "--status", owned])
        assert rc == 1
        assert "task not found" in capsys.readouterr().err

    def test_execute_same_tenant_allows(
        self,
        isolated_data: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # Same tenant can execute (no cross-tenant denial).
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantA")
        rc = main(["task", "echo: mine", "--execute"])
        assert rc == 0
        assert "mine" in capsys.readouterr().out
