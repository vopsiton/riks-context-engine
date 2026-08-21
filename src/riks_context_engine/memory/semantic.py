"""Semantic memory - long-term structured knowledge."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from riks_context_engine.memory.base import MemoryEntry


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


class SemanticMemory:
    """Long-term structured knowledge store.

    Persists facts, concepts, and relationships that are
    accessed repeatedly across sessions.
    """

    def __init__(self, db_path: str | None = None, embedder=None):
        self.db_path = db_path or "data/semantic.db"
        self.embedder = embedder
        self._is_temp = self.db_path.startswith(":") and self.db_path.endswith(":")
        if not self._is_temp:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread, kept open for the lifetime of the
        # object. The previous design opened a fresh sqlite3.connect() per
        # call and leaked (never closed) the connections: under load the
        # fd count grew until the process hit its limit, sqlite3 calls
        # then failed with 'bad parameter or other API misuse' and writes
        # were silently lost. The cross-process test 4 procs x 25 writes
        # exposed this as 'Expected 100 entries, got 75'. (#163)
        self._local = threading.local()
        self._init_db()

    def __del__(self):
        try:
            self._local.conn.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    def _connect(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        """Initialize the SQLite schema."""
        conn = self._connect()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
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
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate)"
        )

    def add(
        self,
        subject: str,
        predicate: str,
        object: str | None = None,
        confidence: float = 1.0,
        embedding: list[float] | None = None,
    ) -> SemanticEntry:
        """Add a semantic knowledge entry."""
        now = datetime.now(timezone.utc)
        # Collision-safe id. The previous id was f"sm_{now.timestamp()}":
        # two concurrent writes whose clock reads fell in the same microsecond
        # produced identical ids and the second INSERT failed with a UNIQUE
        # constraint error, silently losing the entry (observed under the
        # cross-process concurrency test: 'Expected 100 entries, got 75').
        # uuid4 keeps the 'sm_' prefix and never collides across processes.
        entry = SemanticEntry(
            id=f"sm_{uuid.uuid4().hex}",
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            created_at=now,
            last_accessed=now,
            embedding=embedding,
        )
        conn = self._connect()
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
        """Get entry by ID, incrementing access count."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM semantic_entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        entry = self._row_to_entry(row)
        entry.access_count += 1
        entry.last_accessed = datetime.now(timezone.utc)
        conn.execute(
            "UPDATE semantic_entries SET access_count = ?, last_accessed = ? WHERE id = ?",
            (entry.access_count, entry.last_accessed.isoformat(), entry_id),
        )
        conn.commit()
        return entry

    def _row_to_entry(self, row: sqlite3.Row) -> SemanticEntry:
        emb = None
        if row["embedding"]:
            emb = json.loads(row["embedding"])
        return SemanticEntry(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence=row["confidence"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
            access_count=row["access_count"],
            embedding=emb,
        )

    def query(
        self, subject: str | None = None, predicate: str | None = None
    ) -> list[SemanticEntry]:
        """Query semantic memory by subject and/or predicate."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row

        # Escape SQL LIKE wildcards in user input so searches are literal
        # Use ESCAPE clause to treat \ as escape character for LIKE patterns
        def _escape(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        esc_subject = _escape(subject) if subject else None
        esc_predicate = _escape(predicate) if predicate else None

        if esc_subject and esc_predicate:
            rows = conn.execute(
                "SELECT * FROM semantic_entries WHERE subject LIKE ? ESCAPE '\\' AND predicate LIKE ? ESCAPE '\\'",
                (f"%{esc_subject}%", f"%{esc_predicate}%"),
            ).fetchall()
        elif esc_subject:
            rows = conn.execute(
                "SELECT * FROM semantic_entries WHERE subject LIKE ? ESCAPE '\\'",
                (f"%{esc_subject}%",),
            ).fetchall()
        elif esc_predicate:
            rows = conn.execute(
                "SELECT * FROM semantic_entries WHERE predicate LIKE ? ESCAPE '\\'",
                (f"%{esc_predicate}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM semantic_entries").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge using keyword matching."""
        pattern = f"%{query}%"
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM semantic_entries
               WHERE subject LIKE ? COLLATE NOCASE
                  OR predicate LIKE ? COLLATE NOCASE
                  OR object LIKE ? COLLATE NOCASE""",
            (pattern, pattern, pattern),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def to_memory_entry(self) -> MemoryEntry:
        """Convert this SemanticEntry to a generic MemoryEntry.

        Useful for interoperability with the unified MemoryEntry schema
        used across all three memory tiers.

        Returns
        -------
        MemoryEntry
            A MemoryEntry with type=SEMANTIC, content="subject predicate object",
            and importance=confidence.

        Example
        -------
        >>> entry = sem.add("auth_service", "uses", "JWT RS256")
        >>> me = entry.to_memory_entry()
        >>> me.type
        <MemoryType.SEMANTIC: 'semantic'>
        """
        from riks_context_engine.memory.base import MemoryEntry, MemoryType

        return MemoryEntry(
            id=self.id,  # type: ignore[attr-defined]
            type=MemoryType.SEMANTIC,
            content=f"{self.subject} {self.predicate} {self.object or ''}",  # type: ignore[attr-defined]
            importance=self.confidence,  # type: ignore[attr-defined]
            embedding=self.embedding,  # type: ignore[attr-defined]
            access_count=self.access_count,  # type: ignore[attr-defined]
            last_accessed=self.last_accessed,  # type: ignore[attr-defined]
        )

    def __len__(self) -> int:
        conn = self._connect()
        row = conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()
        return row[0] if row else 0

    def delete(self, entry_id: str) -> bool:
        conn = self._connect()
        cur = conn.execute("DELETE FROM semantic_entries WHERE id = ?", (entry_id,))
        conn.commit()
        return cur.rowcount > 0  # type: ignore[no-any-return]
