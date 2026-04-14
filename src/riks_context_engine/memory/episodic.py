"""Episodic memory - session-level, short-term observations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class EpisodicEntry:
    """A single episodic memory entry."""

    id: str
    timestamp: datetime
    content: str
    importance: float  # 0.0 - 1.0
    embedding: list[float] | None = None
    tags: list[str] | None = None


class EpisodicMemory:
    """Session-level, short-term memory store.

    Stores recent observations, conversation snippets, and
    ephemeral facts that don't persist across sessions.
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path or "data/episodic.json"

    def add(self, content: str, importance: float = 0.5, tags: list[str] | None = None) -> EpisodicEntry:
        """Add an episodic memory entry."""
        entry = EpisodicEntry(
            id=f"ep_{datetime.now(timezone.utc).timestamp()}",
            timestamp=datetime.now(timezone.utc),
            content=content,
            importance=importance,
            tags=tags,
        )
        return entry

    def query(self, query: str, limit: int = 10) -> list[EpisodicEntry]:
        """Query episodic memory."""
        return []

    def prune(self, max_entries: int = 1000) -> int:
        """Remove low-importance entries when limit is exceeded."""
        return 0
