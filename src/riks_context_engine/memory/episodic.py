"""Episodic memory - session-level, short-term observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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
        self._entries: dict[str, EpisodicEntry] = {}
        if storage_path != ":memory:":
            Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        """Load entries from JSON file."""
        if self.storage_path == ":memory:":
            return
        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            for item in data:
                entry = EpisodicEntry(
                    id=item["id"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    content=item["content"],
                    importance=item.get("importance", 0.5),
                    embedding=item.get("embedding"),
                    tags=item.get("tags"),
                )
                self._entries[entry.id] = entry
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # Empty store on first run

    def _persist(self) -> None:
        """Write entries to JSON file."""
        if self.storage_path == ":memory:":
            return
        data = []
        for entry in self._entries.values():
            data.append(
                {
                    "id": entry.id,
                    "timestamp": entry.timestamp.isoformat(),
                    "content": entry.content,
                    "importance": entry.importance,
                    "embedding": entry.embedding,
                    "tags": entry.tags,
                }
            )
        with open(self.storage_path, "w") as f:
            json.dump(data, f)

    def add(
        self, content: str, importance: float = 0.5, tags: list[str] | None = None
    ) -> EpisodicEntry:
        """Add an episodic memory entry."""
        entry = EpisodicEntry(
            id=f"ep_{datetime.now(timezone.utc).timestamp()}",
            timestamp=datetime.now(timezone.utc),
            content=content,
            importance=importance,
            tags=tags,
        )
        self._entries[entry.id] = entry
        self._persist()
        return entry

    def get(self, entry_id: str) -> EpisodicEntry | None:
        """Get an episodic entry by ID."""
        return self._entries.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        """Delete an episodic entry by ID."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._persist()
            return True
        return False

    def query(self, query: str, limit: int = 10) -> list[EpisodicEntry]:
        """Query episodic memory by content similarity (substring match)."""
        query_lower = query.lower()
        scored = []
        for entry in self._entries.values():
            if query_lower in entry.content.lower():
                scored.append((entry.importance, entry.timestamp, entry))
        # Sort by importance desc, then newest first
        scored.sort(key=lambda x: (-x[0], -x[1].timestamp()))
        return [entry for _, _, entry in scored[:limit]]

    def prune(self, max_entries: int = 1000) -> int:
        """Remove low-importance entries when limit is exceeded.

        Returns the number of entries pruned.
        """
        if len(self._entries) <= max_entries:
            return 0

        # Sort by importance asc, then oldest first
        entries_by_quality = sorted(
            self._entries.values(),
            key=lambda e: (e.importance, e.timestamp),
        )

        # Remove lowest-importance entries until under limit
        pruned = 0
        to_remove = len(self._entries) - max_entries
        for entry in entries_by_quality:
            if pruned >= to_remove:
                break
            del self._entries[entry.id]
            pruned += 1

        self._persist()
        return pruned
