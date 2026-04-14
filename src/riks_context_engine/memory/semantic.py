"""Semantic memory - long-term structured knowledge."""

from dataclasses import dataclass
from datetime import datetime, timezone


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

    def add(
        self, subject: str, predicate: str, object: str | None = None, confidence: float = 1.0
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
        return entry

    def query(
        self, subject: str | None = None, predicate: str | None = None
    ) -> list[SemanticEntry]:
        """Query semantic memory."""
        return []

    def recall(self, query: str) -> list[SemanticEntry]:
        """Semantic search across knowledge."""
        return []
