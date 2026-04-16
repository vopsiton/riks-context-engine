"""Semantic memory - long-term structured knowledge."""

from __future__ import annotations

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


class SemanticMemory:
    """Long-term structured knowledge store.

    Persists facts, concepts, and relationships that are
    accessed repeatedly across sessions.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or "data/semantic.db"
        self._entries: dict[str, SemanticEntry] = {}
        self._is_memory = db_path == ":memory:"
        if not self._is_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # In-memory: use dict directly, no SQLite needed
        if self._is_memory:
            self._conn = None
        else:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_entries (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            )
        """
            )
            self._conn.commit()
            self._load()

    def _load(self) -> None:
        """Load entries from SQLite into memory."""
        if self._is_memory:
            return
        try:
            conn = self._conn
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            for row in cur.execute("SELECT * FROM semantic_entries"):
                entry = SemanticEntry(
                    id=row["id"],
                    subject=row["subject"],
                    predicate=row["predicate"],
                    object=row["object"],
                    confidence=row["confidence"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    last_accessed=datetime.fromisoformat(row["last_accessed"]),
                    access_count=row["access_count"],
                )
                self._entries[entry.id] = entry
        except sqlite3.OperationalError:
            pass  # Empty/invalid DB on first run

    def add(
        self,
        subject: str,
        predicate: str,
        object: str | None = None,
        confidence: float = 1.0,
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
        )
        self._entries[entry.id] = entry
        self._save_entry(entry)
        return entry

    def _save_entry(self, entry: SemanticEntry) -> None:
        """Persist entry to SQLite using the shared connection."""
        if self._is_memory:
            return
        conn = self._conn
        conn.execute(
            """
            INSERT OR REPLACE INTO semantic_entries
            (id, subject, predicate, object, confidence, created_at, last_accessed, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()

    def get(self, entry_id: str) -> SemanticEntry | None:
        """Get a semantic entry by ID and record access."""
        entry = self._entries.get(entry_id)
        if entry:
            entry.access_count += 1
            entry.last_accessed = datetime.now(timezone.utc)
            self._save_entry(entry)
        return entry

    def delete(self, entry_id: str) -> bool:
        """Delete a semantic entry by ID."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            if not self._is_memory:
                self._conn.execute("DELETE FROM semantic_entries WHERE id = ?", (entry_id,))
                self._conn.commit()
            return True
        return False

    def query(
        self, subject: str | None = None, predicate: str | None = None
    ) -> list[SemanticEntry]:
        """Query semantic memory by subject and/or predicate."""
        results = []
        for entry in self._entries.values():
            match = True
            if subject and subject.lower() not in entry.subject.lower():
                match = False
            if predicate and predicate.lower() not in entry.predicate.lower():
                match = False
            if match:
                results.append(entry)
        return results

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge (simple substring match)."""
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            if (
                query_lower in entry.subject.lower()
                or query_lower in entry.predicate.lower()
                or (entry.object and query_lower in entry.object.lower())
            ):
                results.append(entry)
        return results
