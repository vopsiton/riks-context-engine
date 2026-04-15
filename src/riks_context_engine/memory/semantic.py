"""Semantic memory - long-term structured knowledge."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import sqlite3
import uuid
from contextlib import contextmanager
from collections.abc import Generator


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
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_access(self) -> None:
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticEntry":
        return cls(
            id=data["id"],
            subject=data["subject"],
            predicate=data["predicate"],
            object=data.get("object"),
            confidence=data.get("confidence", 1.0),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
        )


class SemanticMemory:
    """Long-term structured knowledge store.

    Persists facts, concepts, and relationships that are
    accessed repeatedly across sessions.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS semantic_entries (
        id          TEXT PRIMARY KEY,
        subject     TEXT NOT NULL,
        predicate   TEXT NOT NULL,
        object      TEXT,
        confidence  REAL NOT NULL DEFAULT 1.0,
        created_at  TEXT NOT NULL,
        last_accessed TEXT NOT NULL,
        access_count INTEGER NOT NULL DEFAULT 0,
        metadata    TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject);
    CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate);
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or "data/semantic.db"
        self._initialized = False
        self._persist_conn: sqlite3.Connection | None = None

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        if self.db_path == ":memory:":
            self._persist_conn = sqlite3.connect(self.db_path, uri=True)
            self._persist_conn.row_factory = sqlite3.Row
            self._persist_conn.executescript(self._SCHEMA)
            self._persist_conn.commit()
        else:
            path = Path(self.db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.executescript(self._SCHEMA)
            conn.commit()
            conn.close()
        self._initialized = True

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        self._ensure_init()
        if self._persist_conn is not None:
            yield self._persist_conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _generate_id(self) -> str:
        return f"sm_{uuid.uuid4().hex}"

    def add(self, subject: str, predicate: str, object: str | None = None, confidence: float = 1.0) -> SemanticEntry:
        """Add a semantic knowledge entry."""
        now = datetime.now(timezone.utc)
        entry = SemanticEntry(
            id=self._generate_id(),
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            created_at=now,
            last_accessed=now,
        )
        self._upsert(entry)
        return entry

    def _upsert(self, entry: SemanticEntry) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO semantic_entries
                (id, subject, predicate, object, confidence,
                 created_at, last_accessed, access_count, metadata)
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
                    json.dumps(entry.metadata),
                ),
            )
            conn.commit()

    def get(self, entry_id: str) -> SemanticEntry | None:
        """Retrieve an entry by id and record the access."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        if row is None:
            return None
        entry = self._row_to_entry(row)
        entry.record_access()
        self._upsert(entry)
        return entry

    def _row_to_entry(self, row: sqlite3.Row) -> SemanticEntry:
        return SemanticEntry(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence=row["confidence"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
            access_count=row["access_count"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def query(self, subject: str | None = None, predicate: str | None = None, object: str | None = None, limit: int = 20) -> list[SemanticEntry]:
        """Query by exact triple components (ANDed filters)."""
        conditions: list[str] = []
        params: list[Any] = []
        if subject:
            conditions.append("subject = ?")
            params.append(subject)
        if predicate:
            conditions.append("predicate = ?")
            params.append(predicate)
        if object:
            conditions.append("object = ?")
            params.append(object)
        where = " AND ".join(conditions) if conditions else "1=1"

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM semantic_entries WHERE {where} LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge (simple substring match)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM semantic_entries WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ? LIMIT 20",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def update(self, entry_id: str, **fields: Any) -> SemanticEntry | None:
        """Update mutable fields on an existing entry."""
        entry = self.get(entry_id)
        if entry is None:
            return None
        for key, value in fields.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        self._upsert(entry)
        return entry

    def delete(self, entry_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM semantic_entries WHERE id = ?", (entry_id,))
            conn.commit()
            return cur.rowcount > 0

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()[0]
            avg_conf = (
                conn.execute("SELECT AVG(confidence) FROM semantic_entries").fetchone()[0] or 0.0
            )
        return {"total": total, "avg_confidence": avg_conf}

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM semantic_entries")
            conn.commit()