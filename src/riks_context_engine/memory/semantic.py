"""Semantic memory - long-term structured knowledge."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import sqlite3


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
        self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn = lambda: self._shared_conn
        self._init_db()

    def __del__(self):
        self._shared_conn.close()

    def _connect(self):
        return sqlite3.connect(self.db_path)

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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate)")

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
        with self._conn() as conn:
            emb_bytes = json.dumps(embedding) if embedding else None
            conn.execute(
                """
                INSERT INTO semantic_entries
                (id, subject, predicate, object, confidence, created_at, last_accessed, access_count, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (entry.id, entry.subject, entry.predicate, entry.object,
                 entry.confidence, entry.created_at.isoformat(),
                 entry.last_accessed.isoformat(), entry.access_count, emb_bytes),
            )
            conn.commit()
        return entry

    def get(self, entry_id: str) -> SemanticEntry | None:
        """Get entry by ID, incrementing access count."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM semantic_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        if not row:
            return None
        entry = self._row_to_entry(row)
        entry.access_count += 1
        entry.last_accessed = datetime.now(timezone.utc)
        with self._conn() as conn:
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

    def query(self, subject: str | None = None, predicate: str | None = None) -> list[SemanticEntry]:
        """Query semantic memory by subject and/or predicate."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if subject and predicate:
                rows = conn.execute(
                    "SELECT * FROM semantic_entries WHERE subject LIKE ? AND predicate LIKE ?",
                    (f"%{subject}%", f"%{predicate}%"),
                ).fetchall()
            elif subject:
                rows = conn.execute(
                    "SELECT * FROM semantic_entries WHERE subject LIKE ?", (f"%{subject}%",)
                ).fetchall()
            elif predicate:
                rows = conn.execute(
                    "SELECT * FROM semantic_entries WHERE predicate LIKE ?", (f"%{predicate}%",)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM semantic_entries").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge using keyword matching."""
        q = query.lower()
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM semantic_entries").fetchall()
        matches = []
        for r in rows:
            entry = self._row_to_entry(r)
            if (q in entry.subject.lower() or
                q in entry.predicate.lower() or
                (entry.object and q in entry.object.lower())):
                matches.append(entry)
        return matches

    def to_memory_entry(self) -> "riks_context_engine.memory.base.MemoryEntry":
        """Convert to generic MemoryEntry."""
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

    def __len__(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()
        return row[0] if row else 0

    def delete(self, entry_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM semantic_entries WHERE id = ?", (entry_id,))
            conn.commit()
            return cur.rowcount > 0
