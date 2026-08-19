"""Integration tests for `riks memory add` / `riks memory query` (#124).

These run the real CLI functions (main → cmd_memory_add/query → real memory
stores on a tmp dir), not mocks. The memory stores read their paths at
*constructor* time (not import time), so setting env vars per test is enough.
"""

from __future__ import annotations

import sys

import pytest

from riks_context_engine.cli.main import main as cli_main_main


def _run(argv: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = ["riks"] + argv
    try:
        return cli_main_main()
    finally:
        sys.argv = old_argv


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point all CLI storage paths at a fresh tmp dir (default tenant)."""
    monkeypatch.setenv("RIKS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIKS_SEMANTIC_DB", str(tmp_path / "semantic.db"))
    monkeypatch.setenv("RIKS_EPISODIC_JSON", str(tmp_path / "episodic.json"))
    monkeypatch.setenv("RIKS_PROCEDURAL_JSON", str(tmp_path / "procedural.json"))
    monkeypatch.delenv("RIKS_TENANT_ID", raising=False)
    yield


# ─── memory add ───────────────────────────────────────────────────────────────


class TestMemoryAdd:
    def test_episodic_add_writes_to_store(self, tmp_path, capsys):
        rc = _run(["memory", "add", "--type", "episodic", "User asked about shipping"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "added episodic entry" in out
        # The entry must actually be on disk
        data = (tmp_path / "episodic.json").read_text()
        assert "User asked about shipping" in data

    def test_semantic_add_writes_to_store(self, tmp_path, capsys):
        rc = _run(["memory", "add", "--type", "semantic", "Vahit=is=DevSecOps"])
        assert rc == 0
        assert "added semantic entry" in capsys.readouterr().out
        assert (tmp_path / "semantic.db").exists()

    def test_procedural_add_writes_to_store(self, tmp_path, capsys):
        rc = _run(
            [
                "memory",
                "add",
                "--type",
                "procedural",
                "deploy",
                "--steps",
                "docker build\ndocker push",
            ]
        )
        assert rc == 0
        assert "added procedure" in capsys.readouterr().out
        data = (tmp_path / "procedural.json").read_text()
        assert "deploy" in data and "docker push" in data

    def test_episodic_add_missing_content_errors(self, capsys):
        rc = _run(["memory", "add", "--type", "episodic"])
        assert rc != 0
        assert "error:" in capsys.readouterr().err

    def test_semantic_add_missing_equals_errors(self, capsys):
        rc = _run(["memory", "add", "--type", "semantic", "no-equals-here"])
        assert rc != 0
        assert "error:" in capsys.readouterr().err

    def test_procedural_add_missing_name_errors(self, capsys):
        rc = _run(["memory", "add", "--type", "procedural", "--steps", "a\nb"])
        assert rc != 0
        assert "error:" in capsys.readouterr().err

    def test_procedural_add_bad_steps_errors(self, capsys):
        rc = _run(["memory", "add", "--type", "procedural", "deploy", "--steps", "not-json"])
        assert rc != 0
        assert "error:" in capsys.readouterr().err


# ─── memory query ─────────────────────────────────────────────────────────────


class TestMemoryQuery:
    def test_episodic_query_finds_added_entry(self, tmp_path, capsys):
        _run(["memory", "add", "--type", "episodic", "Deploy failed with timeout"])
        rc = _run(["memory", "query", "deploy"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Deploy failed with timeout" in out

    def test_episodic_query_no_match(self, capsys):
        rc = _run(["memory", "query", "zzz_no_such_term_zzz"])
        assert rc == 0
        assert "no episodic matches" in capsys.readouterr().out

    def test_semantic_query_finds_added_entry(self, capsys):
        _run(["memory", "add", "--type", "semantic", "Opsiton=builds=context engines"])
        rc = _run(["memory", "query", "--type", "semantic", "Opsiton"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Opsiton" in out and "builds" in out

    def test_procedural_query_finds_added_entry(self, capsys):
        _run(
            [
                "memory",
                "add",
                "--type",
                "procedural",
                "rollback",
                "--steps",
                "kubectl rollout undo\nverify health",
            ]
        )
        rc = _run(["memory", "query", "--type", "procedural", "rollback"])
        assert rc == 0
        assert "rollback" in capsys.readouterr().out

    def test_query_missing_term_errors(self, capsys):
        rc = _run(["memory", "query"])
        assert rc != 0
        assert "error:" in capsys.readouterr().err


# ─── tenant isolation (mirrors server.py contract #102) ──────────────────────


class TestTenantIsolation:
    def test_tenant_stores_are_isolated(self, tmp_path, monkeypatch, capsys):
        _run(["memory", "add", "--type", "episodic", "default tenant note"])
        monkeypatch.setenv("RIKS_TENANT_ID", "acme")
        # acme tenant must NOT see the default tenant's entry
        rc = _run(["memory", "query", "default"])
        assert rc == 0
        assert "no episodic matches" in capsys.readouterr().out
        # acme writes its own store under data/tenants/acme/
        rc = _run(["memory", "add", "--type", "episodic", "acme note"])
        assert rc == 0
        assert (tmp_path / "tenants" / "acme" / "episodic.json").exists()


# ─── honest not-implemented (no more fake success) ───────────────────────────


class TestNotImplemented:
    def test_context_stats_is_implemented(self, tmp_path, monkeypatch, capsys):
        """ "context stats" now returns real store data (turn 2)."""
        monkeypatch.setenv("RIKS_DATA_DIR", str(tmp_path))
        rc = _run(["context", "stats"])
        assert rc == 0
        assert "messages_total" in capsys.readouterr().out

    def test_task_is_implemented(self, tmp_path, monkeypatch, capsys):
        """ "task <goal>" now queues into the real store (turn 2)."""
        monkeypatch.setenv("RIKS_DATA_DIR", str(tmp_path))
        rc = _run(["task", "do something"])
        assert rc == 0
        assert "task queued" in capsys.readouterr().out

    def test_fake_success_string_gone(self, capsys):
        """The old no-op printed 'Command executed successfully' — must never appear."""
        for argv in (
            ["memory", "add", "--type", "episodic", "x"],
            ["memory", "query", "x"],
            ["context", "stats"],
        ):
            _run(argv)
            capsys.readouterr()
            captured = capsys.readouterr()
            assert "Command executed successfully" not in captured.out
