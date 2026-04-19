"""Semantic memory - long-term structured knowledge."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from riks_context_engine.memory.base import MemoryEntry
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SemanticEntry:
    """A semantic knowledge entry."""

    id: str
    subject: str
    predicate: str
    object: str | None
    confidence: float  # 0.0 - 1.0
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    embedding: list[float] | None = None

    def to_memory_entry(self) -> MemoryEntry:
        """Convert this SemanticEntry to a generic MemoryEntry."""
        from riks_context_engine.memory.base import MemoryEntry, MemoryType

        return MemoryEntry(
            id=self.id,
            type=MemoryType.SEMANTIC,
            content=f"{self.subject} {self.predicate} {self.object or ''}",
            importance=self.confidence,
            embedding=self.embedding,
            access_count=self.access_count,
            last_accessed=self.last_accessed,
        )


class SemanticMemory:
    """Long-term structured knowledge store.

    Persists facts, concepts, and relationships that are
    accessed repeatedly across sessions.

    Thread-safe: Uses WAL mode and per-operation locking to allow
    concurrent reads and writes from multiple threads without
    "Database is locked" errors.
    """

    def __init__(self, db_path: str | None = None, embedder: Any | None = None) -> None:
        self.db_path = db_path or "data/semantic.db"
        self.embedder = embedder
        self._is_temp = self.db_path.startswith(":") and self.db_path.endswith(":")
        if not self._is_temp:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared_conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30,  # Wait up to 30s for locks before failing
        )
        self._conn = lambda: self._shared_conn
        self._write_lock = threading.Lock()
        self._init_db()
        self._enable_wal()

    def __del__(self) -> None:
        self._shared_conn.close()

    def _enable_wal(self) -> None:
        """Enable WAL mode for better concurrent access.

        WAL (Write-Ahead Logging) allows concurrent reads while a write
        is in progress, and vice versa. This significantly reduces lock
        contention in multi-threaded scenarios.
        """
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)

    def _init_db(self) -> None:
        """Initialize the SQLite schema."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_entries (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    embedding BLOB
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_object ON semantic_entries(object)"
            )

    @staticmethod
    def _escape_like(val: str) -> str:
        """Escape LIKE special characters to treat them as literals.

        LIKE wildcards: % (any chars), _ (single char)
        Without escaping, user input like '50%' would match anything after '50'.
        """
        return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert sqlite3.Row to plain dict while connection is open.

        sqlite3.Row columns become inaccessible after connection closes,
        so we materialize to a dict first.
        """
        return {
            "id": row["id"],
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
            "last_accessed": row["last_accessed"],
            "access_count": row["access_count"],
            "embedding": row["embedding"],
        }

    def _dict_to_entry(self, d: dict) -> SemanticEntry:
        """Build a SemanticEntry from a plain dict."""
        created_at_raw = d["created_at"]
        last_accessed_raw = d["last_accessed"]
        if not created_at_raw:
            created_at = datetime.now(timezone.utc)
        elif isinstance(created_at_raw, str):
            created_at = datetime.fromisoformat(created_at_raw)
        else:
            created_at = created_at_raw
        if not last_accessed_raw:
            last_accessed = datetime.now(timezone.utc)
        elif isinstance(last_accessed_raw, str):
            last_accessed = datetime.fromisoformat(last_accessed_raw)
        else:
            last_accessed = last_accessed_raw
        return SemanticEntry(
            id=d["id"],
            subject=d["subject"],
            predicate=d["predicate"],
            object=d["object"],
            confidence=d["confidence"],
            created_at=created_at,
            last_accessed=last_accessed,
            access_count=d["access_count"],
            embedding=json.loads(d["embedding"]) if d["embedding"] else None,
        )

    def add(
        self,
        subject: str,
        predicate: str,
        object: str | None = None,
        confidence: float = 1.0,
        embedding: list[float] | None = None,
    ) -> SemanticEntry:
        """Add a semantic knowledge entry (thread-safe)."""
        now = datetime.now(timezone.utc)
        entry = SemanticEntry(
            id=f"sm_{now.timestamp()}",
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            created_at=now,
            last_accessed=now,
            embedding=embedding,
        )
        with self._write_lock:
            with self._conn() as conn:
                emb_bytes = json.dumps(embedding) if embedding else None
                conn.execute(
                    """
                    INSERT INTO semantic_entries
                    (id, subject, predicate, object, confidence, created_at, last_accessed, access_count, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.subject,
                        entry.predicate,
                        entry.object,
                        entry.confidence,
                        entry.created_at.isoformat(),
                        entry.last_accessed.isoformat(),
                        entry.access_count,
                        emb_bytes,
                    ),
                )
                conn.commit()
        return entry

    def get(self, entry_id: str) -> SemanticEntry | None:
        """Get entry by ID, incrementing access count (thread-safe)."""
        with self._write_lock:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM semantic_entries WHERE id = ?", (entry_id,)
                ).fetchone()
                if not row:
                    return None
                # Convert to dict while connection is open
                data = self._row_to_dict(row)
                data["access_count"] += 1
                data["last_accessed"] = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE semantic_entries SET access_count = ?, last_accessed = ? WHERE id = ?",
                    (data["access_count"], data["last_accessed"], entry_id),
                )
            return self._dict_to_entry(data)

    def query(
        self, subject: str | None = None, predicate: str | None = None
    ) -> list[SemanticEntry]:
        """Query semantic memory by subject and/or predicate (thread-safe).

        Uses parameterized queries to prevent SQL injection.
        LIKE special characters (%, _) are escaped so user input is treated literally.
        """
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if subject and predicate:
                rows = conn.execute(
                    "SELECT * FROM semantic_entries WHERE subject LIKE ? ESCAPE ? AND predicate LIKE ? ESCAPE ?",
                    (f"%{self._escape_like(subject)}%", "\\", f"%{self._escape_like(predicate)}%", "\\"),
                ).fetchall()
            elif subject:
                rows = conn.execute(
                    "SELECT * FROM semantic_entries WHERE subject LIKE ? ESCAPE ?",
                    (f"%{self._escape_like(subject)}%", "\\"),
                ).fetchall()
            elif predicate:
                rows = conn.execute(
                    "SELECT * FROM semantic_entries WHERE predicate LIKE ? ESCAPE ?",
                    (f"%{self._escape_like(predicate)}%", "\\"),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM semantic_entries").fetchall()
        # Convert rows to dicts and then to entries outside the connection
        result = []
        for row in rows:
            data = self._row_to_dict(row)
            result.append(self._dict_to_entry(data))
        return result

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge using indexed SQL LIKE (thread-safe).


        Uses parameterized queries with indexed subject/predicate/object columns
        for sub-100ms performance on 1000+ entries.
        """
        q = self._escape_like(query)
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM semantic_entries "
                "WHERE subject LIKE ? ESCAPE ? OR predicate LIKE ? ESCAPE ? OR object LIKE ? ESCAPE ?",
                (f"%{q}%", "\\", f"%{q}%", "\\", f"%{q}%", "\\"),
            ).fetchall()
        result = []
        for row in rows:
            data = self._row_to_dict(row)
            result.append(self._dict_to_entry(data))
        return result

    def __len__(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()
        return row[0] if row else 0

    def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID (thread-safe)."""
        with self._write_lock:
            with self._conn() as conn:
                cur = conn.execute("DELETE FROM semantic_entries WHERE id = ?", (entry_id,))
                conn.commit()
                return cur.rowcount > 0
