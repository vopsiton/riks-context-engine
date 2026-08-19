"""Data integrity checking for riks-context-engine.

Provides ``check_data_integrity(data_dir)`` which validates every ``*.db``
and ``*.json`` file under *data_dir* (excluding ``data/backups/``).  The
function is importable and used by ``riks doctor`` and the MCP fail-fast
gate.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Problem:
    path: str
    kind: str  # "sqlite" | "json"
    detail: str


def _is_backup_dir(path: Path, data_root: Path) -> bool:
    """Return True if *path* is inside <data_root>/backups/."""
    try:
        path.relative_to(data_root / "backups")
        return True
    except ValueError:
        return False


def check_data_integrity(data_dir: str = "data") -> list[Problem]:
    """Walk *data_dir* and validate every ``*.db`` / ``*.json`` file.

    Skips ``<data_dir>/backups/`` to avoid checking backup artifacts.
    Empty or missing files are **not** treated as problems.
    """
    root = Path(data_dir)
    if not root.is_dir():
        return []

    problems: list[Problem] = []

    for dirpath, _dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        if _is_backup_dir(dp, root):
            continue

        for fname in filenames:
            fpath = dp / fname
            if not fpath.is_file() or fpath.stat().st_size == 0:
                continue

            if fname.endswith(".db"):
                problems.extend(_check_sqlite(fpath))
            elif fname.endswith(".json"):
                problems.extend(_check_json(fpath))

    return problems


def _check_sqlite(path: Path) -> list[Problem]:
    try:
        conn = sqlite3.connect(str(path))
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                detail = result[0] if result else "no result"
                return [Problem(path=str(path), kind="sqlite", detail=detail)]
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        return [Problem(path=str(path), kind="sqlite", detail=str(exc))]
    return []


def _check_json(path: Path) -> list[Problem]:
    try:
        data = path.read_bytes()
        json.loads(data)
    except json.JSONDecodeError as exc:
        return [Problem(path=str(path), kind="json", detail=str(exc))]
    except OSError as exc:
        return [Problem(path=str(path), kind="json", detail=str(exc))]
    return []
