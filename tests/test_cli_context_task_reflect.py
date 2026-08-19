"""Integration tests for CLI turn 2 (#124): context stats/prune/clear, task, reflect.

Each command is exercised against the REAL stores (tmp data dir), not mocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from riks_context_engine.cli.main import main
from riks_context_engine.context.manager import ContextWindowManager


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIKS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RIKS_TENANT_ID", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    return tmp_path


def _seed_context(tmp_path: Path, backdated: int = 0) -> None:
    mgr = ContextWindowManager(storage_path=str(tmp_path / "context.json"))
    mgr.add("user", "fresh question", importance=0.9)
    mgr.add("assistant", "fresh answer", importance=0.8)
    for _ in range(backdated):
        m = mgr.add("user", "old message", importance=0.2)
        m.timestamp = datetime.now(timezone.utc) - timedelta(days=10)
    mgr._auto_save()


class TestContextStats:
    def test_stats_empty(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        rc = main(["context", "stats"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "messages_total: 0" in out
        assert "current_tokens: 0" in out

    def test_stats_with_data_and_role_distribution(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        _seed_context(isolated_data, backdated=1)
        rc = main(["context", "stats"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "messages_total: 3" in out
        assert "user=2" in out
        assert "assistant=1" in out

    def test_stats_tenant_scoped(
        self,
        isolated_data: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        _seed_context(isolated_data)
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantA")
        rc = main(["context", "stats"])
        assert rc == 0
        assert "messages_total: 0" in capsys.readouterr().out  # tenantB has none


class TestContextPrune:
    def test_prune_removes_old_messages(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        _seed_context(isolated_data, backdated=2)
        rc = main(["context", "prune", "--older-than", "7"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "pruned 2 message(s)" in out
        # persisted state: only the 2 fresh messages remain
        data = json.loads((isolated_data / "context.json").read_text())
        assert len(data["messages"]) == 2

    def test_prune_with_type_filter(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        _seed_context(isolated_data, backdated=1)
        rc = main(["context", "prune", "--older-than", "7", "--type", "user"])
        assert rc == 0
        assert "pruned 1 message(s)" in capsys.readouterr().out
        # the old user message is gone; fresh user + fresh assistant remain
        data = json.loads((isolated_data / "context.json").read_text())
        assert len(data["messages"]) == 2

    def test_prune_requires_older_than(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        rc = main(["context", "prune"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err

    def test_prune_negative_days_rejected(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        rc = main(["context", "prune", "--older-than", "-1"])
        assert rc == 1


class TestContextClear:
    def test_clear_requires_confirmation(
        self,
        isolated_data: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        _seed_context(isolated_data)
        monkeypatch.setattr("builtins.input", lambda *a: "n")
        rc = main(["context", "clear"])
        assert rc == 1
        assert "aborted" in capsys.readouterr().err
        data = json.loads((isolated_data / "context.json").read_text())
        assert len(data["messages"]) == 2  # untouched

    def test_clear_with_yes(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        _seed_context(isolated_data, backdated=1)
        rc = main(["context", "clear", "--yes"])
        assert rc == 0
        assert "cleared 3 message(s)" in capsys.readouterr().out
        data = json.loads((isolated_data / "context.json").read_text())
        assert len(data["messages"]) == 0

    def test_clear_without_tty_aborts(self, isolated_data: Path, monkeypatch: pytest.MonkeyPatch):
        """No --yes and no interactive input (EOF) → abort, no traceback."""
        _seed_context(isolated_data)

        def _eof(*a: Any) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", _eof)
        rc = main(["context", "clear"])
        assert rc == 1


class TestTask:
    def test_task_add_persists(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        rc = main(["task", "deploy staging"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "task queued:" in out
        data = json.loads((isolated_data / "tasks.json").read_text())
        assert data["tasks"][0]["goal"] == "deploy staging"
        assert data["tasks"][0]["status"] == "queued"

    def test_task_execute_flag_removed(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        # #124: `--execute` was a no-op (never executed) and was removed; the
        # task model must be clarified before real execution lands. The CLI
        # is fail-closed about unknown options: it must refuse (exit 2), not
        # silently queue and exit 0.
        rc = main(["task", "build pipeline", "--execute"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "unexpected argument(s)" in err
        assert "--execute" in err
        assert not (isolated_data / "tasks.json").exists()

    def test_task_list(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        main(["task", "goal one"])
        main(["task", "goal two"])
        rc = main(["task", "--list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "goal one" in out and "goal two" in out

    def test_task_list_empty(self, isolated_data: Path, capsys: pytest.CaptureFixture[str]):
        rc = main(["task", "--list"])
        assert rc == 0
        assert "empty" in capsys.readouterr().out

    def test_task_requires_goal_or_list(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        rc = main(["task"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err

    def test_task_tenant_scoped(self, isolated_data: Path, monkeypatch: pytest.MonkeyPatch):
        main(["task", "shared goal"])
        monkeypatch.setenv("RIKS_TENANT_ID", "tenantX")
        rc = main(["task", "--list"])
        assert rc == 0
        # tenantX queue file (if any) must not contain the shared-tenant task
        tenant_tasks = isolated_data / "tenants" / "tenantX" / "tasks.json"
        if tenant_tasks.exists():
            assert "shared goal" not in tenant_tasks.read_text()


class TestReflect:
    def test_reflect_with_transcript_writes_lessons(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        transcript = isolated_data / "transcript.json"
        transcript.write_text(
            json.dumps(
                [
                    {"role": "user", "content": "please deploy the service"},
                    {
                        "role": "assistant",
                        "content": "deploy failed: permission denied, tool error",
                    },
                ]
            )
        )
        rc = main(["reflect", "--session", "sess-42", "--transcript", str(transcript)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "reflection: session=sess-42" in out
        assert "lessons:" in out
        # real persistence: lessons.json written
        data = json.loads((isolated_data / "lessons.json").read_text())
        assert data["lessons"], "at least one lesson must be persisted"

    def test_reflect_empty_context_and_no_transcript_is_error(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        rc = main(["reflect", "--session", "sess-empty"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err

    def test_reflect_from_context_window(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        _seed_context(isolated_data)
        rc = main(["reflect", "--session", "sess-ctx"])
        assert rc == 0
        assert "session=sess-ctx" in capsys.readouterr().out

    def test_reflect_bad_transcript_is_error(
        self, isolated_data: Path, capsys: pytest.CaptureFixture[str]
    ):
        bad = isolated_data / "bad.json"
        bad.write_text("{not json")
        rc = main(["reflect", "--session", "s1", "--transcript", str(bad)])
        assert rc == 1
        assert "error:" in capsys.readouterr().err
