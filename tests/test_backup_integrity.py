"""Tests for backup + integrity (#105)."""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_repo_root / "scripts"))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Create a minimal data directory with one .db and one .json file."""
    d = tmp_path / "data"
    d.mkdir()

    conn = sqlite3.connect(str(d / "semantic.db"))
    conn.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO facts VALUES (1, 'hello')")
    conn.commit()
    conn.close()

    (d / "episodic.json").write_text(json.dumps({"entries": []}))

    tenant_dir = d / "tenants" / "acme"
    tenant_dir.mkdir(parents=True)
    conn2 = sqlite3.connect(str(tenant_dir / "semantic.db"))
    conn2.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, text TEXT)")
    conn2.commit()
    conn2.close()
    (tenant_dir / "episodic.json").write_text(json.dumps({"entries": []}))

    return d


# ---------------------------------------------------------------------------
# 1. Backup creates files in the correct relative structure
# ---------------------------------------------------------------------------


class TestBackupCreation:
    def test_backup_preserves_relative_structure(self, data_dir: Path) -> None:
        from backup import run_backup

        snapshot = run_backup(data_dir=str(data_dir), keep=7)

        assert (snapshot / "semantic.db").exists()
        assert (snapshot / "episodic.json").exists()
        assert (snapshot / "tenants" / "acme" / "semantic.db").exists()
        assert (snapshot / "tenants" / "acme" / "episodic.json").exists()

    def test_backup_excludes_backups_dir(self, data_dir: Path) -> None:
        """data/backups/ must not be included in subsequent backups."""
        from backup import run_backup

        run_backup(data_dir=str(data_dir), keep=7)
        time.sleep(1.1)
        snap2 = run_backup(data_dir=str(data_dir), keep=7)

        for child in snap2.rglob("*"):
            rel = child.relative_to(snap2)
            assert not str(rel).startswith("backups"), (
                f"backup dir leaked into snapshot: {rel}"
            )


# ---------------------------------------------------------------------------
# 2. Atomicity: SQLite backup via Connection.backup, NOT shutil.copy/cp
# ---------------------------------------------------------------------------


class TestAtomicSQLiteBackup:
    def test_backup_uses_connection_backup_api(self) -> None:
        """Verify the backup module uses sqlite3.Connection.backup, not shutil.copy."""
        import backup

        src = inspect.getsource(backup)
        assert "shutil.copy" not in src, "backup must not use shutil.copy for .db files"
        assert ".backup(" in src, "backup must use Connection.backup for .db files"

    def test_concurrent_write_during_backup(self, data_dir: Path) -> None:
        """Backup taken while another thread writes should pass integrity_check."""
        from backup import run_backup

        db_path = str(data_dir / "semantic.db")
        stop = threading.Event()

        def writer() -> None:
            conn = sqlite3.connect(db_path)
            i = 100
            while not stop.is_set():
                try:
                    conn.execute("INSERT INTO facts VALUES (?, ?)", (i, f"row-{i}"))
                    conn.commit()
                except sqlite3.Error:
                    pass
                i += 1
                time.sleep(0.001)
            conn.close()

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            time.sleep(0.02)
            snapshot = run_backup(data_dir=str(data_dir), keep=7)
        finally:
            stop.set()
            t.join(timeout=2)

        backup_db = str(snapshot / "semantic.db")
        conn = sqlite3.connect(backup_db)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        assert result is not None and result[0] == "ok"


# ---------------------------------------------------------------------------
# 3. Retention
# ---------------------------------------------------------------------------


class TestRetention:
    def test_keep_3_from_5(self, data_dir: Path) -> None:
        from backup import run_backup

        for _ in range(5):
            run_backup(data_dir=str(data_dir), keep=3)
            time.sleep(1.1)

        backups_dir = data_dir / "backups"
        dirs = [d for d in backups_dir.iterdir() if d.is_dir()]
        assert len(dirs) == 3

    def test_keep_0_disables_rotation(self, data_dir: Path) -> None:
        from backup import run_backup

        for _ in range(5):
            run_backup(data_dir=str(data_dir), keep=0)
            time.sleep(1.1)

        backups_dir = data_dir / "backups"
        dirs = [d for d in backups_dir.iterdir() if d.is_dir()]
        assert len(dirs) == 5


# ---------------------------------------------------------------------------
# 4. Integrity checking
# ---------------------------------------------------------------------------


class TestCheckDataIntegrity:
    def test_clean_data_returns_empty(self, data_dir: Path) -> None:
        from riks_context_engine.integrity import check_data_integrity

        problems = check_data_integrity(str(data_dir))
        assert problems == []

    def test_corrupt_json_detected(self, data_dir: Path) -> None:
        from riks_context_engine.integrity import check_data_integrity

        (data_dir / "episodic.json").write_text("{broken json!!!")
        problems = check_data_integrity(str(data_dir))
        json_problems = [p for p in problems if p.kind == "json"]
        assert len(json_problems) >= 1

    def test_corrupt_db_detected(self, data_dir: Path) -> None:
        from riks_context_engine.integrity import check_data_integrity

        db_path = data_dir / "semantic.db"
        with open(db_path, "r+b") as f:
            f.seek(100)
            f.write(b"\x00" * 200)

        problems = check_data_integrity(str(data_dir))
        db_problems = [p for p in problems if p.kind == "sqlite"]
        assert len(db_problems) >= 1

    def test_empty_files_not_problems(self, data_dir: Path) -> None:
        from riks_context_engine.integrity import check_data_integrity

        (data_dir / "empty.json").write_text("")
        problems = check_data_integrity(str(data_dir))
        empty_probs = [p for p in problems if "empty.json" in p.path]
        assert len(empty_probs) == 0

    def test_skips_backup_dir(self, data_dir: Path) -> None:
        from riks_context_engine.integrity import check_data_integrity

        bk = data_dir / "backups" / "2099-01-01T00-00-00Z"
        bk.mkdir(parents=True)
        (bk / "corrupt.json").write_text("{bad")
        problems = check_data_integrity(str(data_dir))
        assert all("backups" not in p.path for p in problems)

    def test_both_corrupt_types_reported(self, data_dir: Path) -> None:
        from riks_context_engine.integrity import check_data_integrity

        (data_dir / "episodic.json").write_text("not json")
        db_path = data_dir / "semantic.db"
        with open(db_path, "r+b") as f:
            f.seek(100)
            f.write(b"\x00" * 200)

        problems = check_data_integrity(str(data_dir))
        kinds = {p.kind for p in problems}
        assert "json" in kinds
        assert "sqlite" in kinds


# ---------------------------------------------------------------------------
# 5. riks doctor CLI
# ---------------------------------------------------------------------------


class TestRiksDoctor:
    def test_clean_data_exit_0(self, data_dir: Path) -> None:
        from riks_context_engine.cli.main import main

        os.environ["RIKS_DATA_DIR"] = str(data_dir)
        try:
            rc = main(["doctor"])
        finally:
            os.environ.pop("RIKS_DATA_DIR", None)
        assert rc == 0

    def test_corrupt_data_exit_1_with_backup_hint(self, data_dir: Path) -> None:
        from backup import run_backup

        from riks_context_engine.cli.main import main

        run_backup(data_dir=str(data_dir), keep=7)

        (data_dir / "episodic.json").write_text("{broken")

        os.environ["RIKS_DATA_DIR"] = str(data_dir)
        try:
            rc = main(["doctor"])
        finally:
            os.environ.pop("RIKS_DATA_DIR", None)
        assert rc == 1

    def test_doctor_does_not_modify_files(self, data_dir: Path) -> None:
        (data_dir / "episodic.json").write_text("{broken")

        mtimes_before = {}
        for f in data_dir.rglob("*"):
            if f.is_file():
                mtimes_before[str(f)] = f.stat().st_mtime

        from riks_context_engine.cli.main import main

        os.environ["RIKS_DATA_DIR"] = str(data_dir)
        try:
            main(["doctor"])
        finally:
            os.environ.pop("RIKS_DATA_DIR", None)

        for f in data_dir.rglob("*"):
            if f.is_file():
                assert mtimes_before.get(str(f)) == f.stat().st_mtime, (
                    f"doctor modified {f}"
                )


# ---------------------------------------------------------------------------
# 6. MCP fail-fast
# ---------------------------------------------------------------------------


class TestMCPIntegrityGate:
    def test_mcp_exits_on_corrupt_data(self, data_dir: Path) -> None:
        (data_dir / "episodic.json").write_text("{broken")

        env = os.environ.copy()
        env["RIKS_DATA_DIR"] = str(data_dir)
        env.pop("RIKS_SKIP_INTEGRITY_CHECK", None)

        result = subprocess.run(
            [sys.executable, "-m", "riks_context_engine.mcp.server"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 1
        assert "integrity" in result.stderr.lower()

    def test_mcp_starts_with_skip_env(self, data_dir: Path) -> None:
        (data_dir / "episodic.json").write_text("{broken")

        env = os.environ.copy()
        env["RIKS_DATA_DIR"] = str(data_dir)
        env["RIKS_SKIP_INTEGRITY_CHECK"] = "1"

        result = subprocess.run(
            [sys.executable, "-m", "riks_context_engine.mcp.server"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
