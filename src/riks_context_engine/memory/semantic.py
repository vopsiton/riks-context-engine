"""Semantic memory - long-term structured knowledge with vector search."""

from __future__ import annotations

import math
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import MemoryEntry, MemoryType
from .embedding import OllamaEmbedder, get_embedder


@dataclass
class SemanticEntry:
    """A semantic knowledge entry (subject–predicate–object triple)."""

    id: str
    subject: str
    predicate: str
    object: str | None
    confidence: float  # 0.0 – 1.0
    embedding: list[float] | None
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.access_count = max(0, int(self.access_count))

    def record_access(self) -> None:
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)

    def to_memory_entry(self) -> MemoryEntry:
        return MemoryEntry(
            id=self.id,
            type=MemoryType.SEMANTIC,
            content=f"{self.subject} {self.predicate} {self.object or ''}".strip(),
            timestamp=self.created_at,
            importance=self.confidence,
            embedding=self.embedding,
            access_count=self.access_count,
            last_accessed=self.last_accessed,
            metadata=self.metadata,
        )

    @classmethod
    def from_memory_entry(cls, me: MemoryEntry) -> SemanticEntry:
        parts = me.content.split(" ", 2)
        subject = parts[0] if len(parts) > 0 else ""
        predicate = parts[1] if len(parts) > 1 else ""
        obj = parts[2] if len(parts) > 2 else None
        return cls(
            id=me.id,
            subject=subject,
            predicate=predicate,
            object=obj,
            confidence=me.importance,
            embedding=me.embedding,
            created_at=me.timestamp,
            last_accessed=me.last_accessed or me.timestamp,
            access_count=me.access_count,
            metadata=me.metadata,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "confidence": self.confidence,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SemanticEntry:
        return cls(
            id=data["id"],
            subject=data["subject"],
            predicate=data["predicate"],
            object=data.get("object"),
            confidence=data.get("confidence", 1.0),
            embedding=data.get("embedding"),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
        )


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticMemory:
    """Long-term structured knowledge store with vector search.

    Persists facts, concepts, and relationships. Each entry optionally
    carries a vector embedding for semantic similarity search.
    Uses SQLite for durable, queryable storage.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS semantic_entries (
        id          TEXT PRIMARY KEY,
        subject     TEXT NOT NULL,
        predicate   TEXT NOT NULL,
        object      TEXT,
        confidence  REAL NOT NULL DEFAULT 1.0,
        embedding   BLOB,
        created_at  TEXT NOT NULL,
        last_accessed TEXT NOT NULL,
        access_count INTEGER NOT NULL DEFAULT 0,
        metadata    TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_entries(subject);
    CREATE INDEX IF NOT EXISTS idx_semantic_predicate ON semantic_entries(predicate);
    """

    def __init__(
        self,
        db_path: str | None = None,
        embedder: OllamaEmbedder | None = None,
        embedding_dim: int = 768,
    ):
        self.db_path = db_path or "data/semantic.db"
        self._embedder = embedder
        self.embedding_dim = embedding_dim
        self._init_db()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(self._SCHEMA)
            conn.commit()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _generate_id(self) -> str:
        return f"sm_{uuid.uuid4().hex}"

    @property
    def embedder(self) -> OllamaEmbedder:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def set_embedder(self, embedder: OllamaEmbedder) -> None:
        self._embedder = embedder

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        subject: str,
        predicate: str,
        object: str | None = None,
        confidence: float = 1.0,
        generate_embedding: bool = True,
    ) -> SemanticEntry:
        """Add a semantic knowledge entry.

        Parameters
        ----------
        subject, predicate, object : str
            The subject–predicate–[object] triple.
        confidence : float
            How certain this fact is (0.0–1.0), also used as importance.
        generate_embedding : bool
            If True, call the Ollama embedder to generate a vector.

        Returns
        -------
        SemanticEntry
        """
        now = datetime.now(timezone.utc)
        embedding: list[float] | None = None
        if generate_embedding:
            text = f"{subject} {predicate} {object or ''}"
            try:
                result = self.embedder.embed(text)
                embedding = result.embedding
            except Exception:  # pragma: no cover – embedder may be unavailable in tests
                embedding = None

        entry = SemanticEntry(
            id=self._generate_id(),
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            embedding=embedding,
            created_at=now,
            last_accessed=now,
        )
        self._upsert(entry)
        return entry

    def _upsert(self, entry: SemanticEntry) -> None:
        with self._conn() as conn:
            import json

            embedding_bytes = json.dumps(entry.embedding).encode() if entry.embedding else None
            conn.execute(
                """
                INSERT OR REPLACE INTO semantic_entries
                (id, subject, predicate, object, confidence, embedding,
                 created_at, last_accessed, access_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.subject,
                    entry.predicate,
                    entry.object,
                    entry.confidence,
                    embedding_bytes,
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
        import json

        embedding_bytes = row["embedding"]
        embedding: list[float] | None = None
        if embedding_bytes:
            embedding = json.loads(embedding_bytes.decode())
        return SemanticEntry(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence=row["confidence"],
            embedding=embedding,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
            access_count=row["access_count"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
        limit: int = 20,
    ) -> list[SemanticEntry]:
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

    def recall(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.0,
    ) -> list[tuple[SemanticEntry, float]]:
        """Semantic search: find entries most similar to the query string.

        Returns entries sorted by cosine similarity to the query embedding,
        dropping those below ``min_similarity``.
        """
        try:
            query_emb = self.embedder.embed(query).embedding
        except Exception:  # pragma: no cover – embedder may be unavailable
            return []

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM semantic_entries WHERE embedding IS NOT NULL"
            ).fetchall()

        scored: list[tuple[SemanticEntry, float]] = []
        for row in rows:
            entry = self._row_to_entry(row)
            if entry.embedding:
                sim = _cosine_sim(query_emb, entry.embedding)
                if sim >= min_similarity:
                    entry.record_access()
                    self._upsert(entry)
                    scored.append((entry, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

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
            with_emb = conn.execute(
                "SELECT COUNT(*) FROM semantic_entries WHERE embedding IS NOT NULL"
            ).fetchone()[0]
        return {
            "total": total,
            "avg_confidence": avg_conf,
            "with_embedding": with_emb,
        }

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM semantic_entries")
            conn.commit()
