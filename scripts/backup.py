#!/usr/bin/env python3
"""Atomic backup of all *.db and *.json files under RIKS_DATA_DIR.

Pure-stdlib Python — no extra dependencies.

Usage:
    python scripts/backup.py

Environment:
    RIKS_DATA_DIR      data directory to back up (default: data)
    RIKS_BACKUP_KEEP   number of snapshots to retain (default: 7, 0 = no rotation)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
MAX_JSON_RETRIES = 3


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())


def _is_backup_dir(path: Path, data_root: Path) -> bool:
    try:
        path.relative_to(data_root / "backups")
        return True
    except ValueError:
        return False


def _collect_files(data_root: Path) -> list[Path]:
    """Collect all *.db and *.json files, skipping backups/."""
    result: list[Path] = []
    for dirpath, _dirs, filenames in os.walk(data_root):
        dp = Path(dirpath)
        if _is_backup_dir(dp, data_root):
            continue
        for fname in filenames:
            if fname.endswith((".db", ".json")):
                result.append(dp / fname)
    return sorted(result)


def _backup_sqlite(src: Path, dst: Path) -> None:
    """Back up a SQLite database using the online backup API (NOT cp)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
        result = dst_conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            detail = result[0] if result else "no result"
            raise RuntimeError(f"integrity check failed on backup of {src}: {detail}")
    finally:
        dst_conn.close()
        src_conn.close()


def _backup_json(src: Path, dst: Path) -> None:
    """Back up a JSON file with parse validation and atomic write."""
    dst.parent.mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for _attempt in range(MAX_JSON_RETRIES):
        try:
            raw = src.read_bytes()
            data = json.loads(raw)
            break
        except (json.JSONDecodeError, OSError) as exc:
            last_exc = exc
            time.sleep(0.05)
    else:
        raise RuntimeError(
            f"JSON validation failed for {src} after {MAX_JSON_RETRIES} retries: {last_exc}"
        )

    fd, tmp_path = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, str(dst))
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _rotate_backups(backup_root: Path, keep: int) -> None:
    """Remove old backup snapshots, keeping only the *keep* newest."""
    if keep <= 0:
        return
    dirs = sorted(
        [d for d in backup_root.iterdir() if d.is_dir() and TIMESTAMP_RE.match(d.name)],
        key=lambda d: d.name,
        reverse=True,
    )
    for old in dirs[keep:]:
        shutil.rmtree(old)


def run_backup(data_dir: str = "data", keep: int = 7) -> Path:
    """Execute a full backup and return the snapshot directory path."""
    data_root = Path(data_dir).resolve()
    if not data_root.is_dir():
        print(f"error: data directory does not exist: {data_root}", file=sys.stderr)
        sys.exit(1)

    files = _collect_files(data_root)
    if not files:
        print("nothing to back up", file=sys.stderr)
        sys.exit(0)

    timestamp = _utc_timestamp()
    snapshot_dir = data_root / "backups" / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for fpath in files:
        rel = fpath.relative_to(data_root)
        dst = snapshot_dir / rel
        try:
            if fpath.suffix == ".db":
                _backup_sqlite(fpath, dst)
            else:
                _backup_json(fpath, dst)
            print(f"  ok  {rel}")
        except Exception as exc:
            msg = f"FAIL {rel}: {exc}"
            print(f"  {msg}", file=sys.stderr)
            errors.append(msg)

    backup_root = data_root / "backups"
    _rotate_backups(backup_root, keep)

    if errors:
        print(f"\nbackup completed with {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nbackup complete: {snapshot_dir}")
    return snapshot_dir


def main() -> None:
    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    keep_raw = os.environ.get("RIKS_BACKUP_KEEP", "7")
    try:
        keep = int(keep_raw)
    except ValueError:
        print(f"error: RIKS_BACKUP_KEEP must be an integer, got '{keep_raw}'", file=sys.stderr)
        sys.exit(1)

    run_backup(data_dir=data_dir, keep=keep)


if __name__ == "__main__":
    main()
