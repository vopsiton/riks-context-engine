"""PostgreSQL-backed semantic memory store (optional backend).

Drop-in replacement for :class:`~riks_context_engine.memory.semantic.SemanticMemory`
when a shared, multi-process, or horizontally-scaled store is needed instead
of a local SQLite file. Requires the ``postgres`` extra::

    pip install riks-context-engine[postgres]
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from riks_context_engine.memory.semantic import SemanticEntry

if TYPE_CHECKING:
    from riks_context_engine.memory.base import MemoryEntry

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "PostgresSemanticMemory requires the 'postgres' extra: "
        "pip install riks-context-engine[postgres]"
    ) from exc

_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_entries (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL,
    last_accessed TIMESTAMPTZ NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    embedding JSONB
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate)",
)


class PostgresSemanticMemory:
    """Long-term structured knowledge store backed by PostgreSQL.

    Mirrors the public interface of
    :class:`~riks_context_engine.memory.semantic.SemanticMemory` (``add``,
    ``get``, ``query``, ``recall``, ``delete``, ``__len__``) so the two are
    interchangeable wherever a semantic memory store is expected.
    """

    def __init__(self, dsn: str, embedder: Any = None):
        self.dsn = dsn
        self.embedder = embedder
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._init_db()

    def __del__(self):
        conn = getattr(self, "_conn", None)
        if conn is not None and not conn.closed:
            conn.close()

    def _init_db(self) -> None:
        """Initialize the PostgreSQL schema."""
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
            for stmt in _INDEXES:
                cur.execute(stmt)

    def add(
        self,
        subject: str,
        predicate: str,
        object: str | None = None,
        confidence: float = 1.0,
        embedding: list[float] | None = None,
        id: str | None = None,
    ) -> SemanticEntry:
        """Add a semantic knowledge entry.

        ``id`` is preserved when explicitly given (e.g. by the import path,
        #180); otherwise a uuid id is generated as before.
        """
        now = datetime.now(timezone.utc)
        # uuid4 id: the former f"sm_{now.timestamp()}" collided when concurrent
        # writes shared a microsecond (UNIQUE constraint failure, entry loss).
        entry = SemanticEntry(
            id=id if id is not None else f"sm_{uuid.uuid4().hex}",
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            created_at=now,
            last_accessed=now,
            embedding=embedding,
        )
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO semantic_entries
                (id, subject, predicate, object, confidence, created_at, last_accessed, access_count, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry.id,
                    entry.subject,
                    entry.predicate,
                    entry.object,
                    entry.confidence,
                    entry.created_at,
                    entry.last_accessed,
                    entry.access_count,
                    Jsonb(embedding) if embedding else None,
                ),
            )
        return entry

    def get(self, entry_id: str) -> SemanticEntry | None:
        """Get entry by ID, incrementing access count."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM semantic_entries WHERE id = %s", (entry_id,))
            row = cur.fetchone()
        if not row:
            return None
        entry = self._row_to_entry(row)
        entry.access_count += 1
        entry.last_accessed = datetime.now(timezone.utc)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE semantic_entries SET access_count = %s, last_accessed = %s WHERE id = %s",
                (entry.access_count, entry.last_accessed, entry_id),
            )
        return entry

    def _row_to_entry(self, row: dict[str, Any]) -> SemanticEntry:
        # psycopg deserializes JSONB columns to Python objects automatically,
        # unlike the sqlite3 backend which stores embeddings as raw JSON text.
        return SemanticEntry(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
            embedding=row["embedding"],
        )

    def query(
        self, subject: str | None = None, predicate: str | None = None
    ) -> list[SemanticEntry]:
        """Query semantic memory by subject and/or predicate."""

        def _escape(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        conditions = []
        params: list[str] = []
        if subject:
            conditions.append("subject ILIKE %s ESCAPE '\\'")
            params.append(f"%{_escape(subject)}%")
        if predicate:
            conditions.append("predicate ILIKE %s ESCAPE '\\'")
            params.append(f"%{_escape(predicate)}%")

        sql = "SELECT * FROM semantic_entries"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_entry(r) for r in rows]

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge using keyword matching."""
        q = query.lower()
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM semantic_entries")
            rows = cur.fetchall()
        matches = []
        for row in rows:
            entry = self._row_to_entry(row)
            if (
                q in entry.subject.lower()
                or q in entry.predicate.lower()
                or (entry.object and q in entry.object.lower())
            ):
                matches.append(entry)
        return matches

    def to_memory_entry(self, entry: SemanticEntry) -> MemoryEntry:
        """Convert a :class:`SemanticEntry` to the generic :class:`MemoryEntry` schema."""
        from riks_context_engine.memory.base import MemoryEntry, MemoryType

        return MemoryEntry(
            id=entry.id,
            type=MemoryType.SEMANTIC,
            content=f"{entry.subject} {entry.predicate} {entry.object or ''}",
            importance=entry.confidence,
            embedding=entry.embedding,
            access_count=entry.access_count,
            last_accessed=entry.last_accessed,
        )

    def __len__(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM semantic_entries")
            row = cur.fetchone()
        return row["count"] if row else 0

    def delete(self, entry_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM semantic_entries WHERE id = %s", (entry_id,))
            rowcount: int = int(cur.rowcount or 0)
            return rowcount > 0
