"""Episodic memory - session-level, short-term observations."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .base import MemoryEntry, MemoryType


@dataclass
class EpisodicEntry:
    """A single episodic memory entry (session observation)."""

    id: str
    timestamp: datetime
    content: str
    importance: float  # 0.0 – 1.0
    embedding: list[float] | None = None
    tags: list[str] | None = None
    access_count: int = 0
    last_accessed: datetime | None = None

    def record_access(self) -> None:
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)

    def to_memory_entry(self) -> MemoryEntry:
        return MemoryEntry(
            id=self.id,
            type=MemoryType.EPISODIC,
            content=self.content,
            timestamp=self.timestamp,
            importance=self.importance,
            embedding=self.embedding,
            access_count=self.access_count,
            last_accessed=self.last_accessed,
            metadata={"tags": self.tags or []},
        )

    @classmethod
    def from_memory_entry(cls, me: MemoryEntry) -> EpisodicEntry:
        return cls(
            id=me.id,
            timestamp=me.timestamp,
            content=me.content,
            importance=me.importance,
            embedding=me.embedding,
            tags=me.metadata.get("tags"),
            access_count=me.access_count,
            last_accessed=me.last_accessed,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "importance": self.importance,
            "embedding": self.embedding,
            "tags": self.tags,
            "access_count": self.access_count,
            "last_accessed": (
                self.last_accessed.isoformat() if self.last_accessed else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> EpisodicEntry:
        ts = data["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        last_accessed = data.get("last_accessed")
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
        return cls(
            id=data["id"],
            timestamp=ts,
            content=data["content"],
            importance=data.get("importance", 0.5),
            embedding=data.get("embedding"),
            tags=data.get("tags"),
            access_count=data.get("access_count", 0),
            last_accessed=last_accessed,
        )


class EpisodicMemory:
    """Session-level, short-term memory store.

    Stores recent observations, conversation snippets, and ephemeral
    facts that don't need to persist across sessions. Backed by a
    JSON file for durability within a session.
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path or "data/episodic.json"
        self._entries: dict[str, EpisodicEntry] = {}
        self._load()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load entries from the JSON file if it exists."""
        path = Path(self.storage_path)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._entries = {
                    d["id"]: EpisodicEntry.from_dict(d) for d in data
                }
            except (json.JSONDecodeError, KeyError, ValueError):
                # Corrupt file – start fresh
                self._entries = {}

    def _save(self) -> None:
        """Persist all entries to the JSON file."""
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [entry.to_dict() for entry in self._entries.values()]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    def _generate_id(self) -> str:
        return f"ep_{uuid.uuid4().hex}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        importance: float = 0.5,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> EpisodicEntry:
        """Add an episodic memory entry.

        Parameters
        ----------
        content : str
            The observation or fact to store.
        importance : float
            Significance in [0.0, 1.0]. Higher values survive pruning.
        tags : list[str] | None
            Optional labels for filtering.
        embedding : list[float] | None
            Optional vector representation.

        Returns
        -------
        EpisodicEntry
            The newly created entry.
        """
        entry = EpisodicEntry(
            id=self._generate_id(),
            timestamp=datetime.now(timezone.utc),
            content=content,
            importance=importance,
            tags=tags or [],
            embedding=embedding,
        )
        self._entries[entry.id] = entry
        self._save()
        return entry

    def get(self, entry_id: str) -> EpisodicEntry | None:
        """Retrieve a specific entry and record the access."""
        entry = self._entries.get(entry_id)
        if entry is not None:
            entry.record_access()
            self._save()
        return entry

    def query(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[EpisodicEntry]:
        """Return recent entries, optionally filtered by tags.

        Parameters
        ----------
        query : str | None
            If provided, performs a simple text-in-content match.
        tags : list[str] | None
            If provided, entries must contain all of these tags.
        limit : int
            Maximum number of entries to return (most recent first).

        Returns
        -------
        list[EpisodicEntry]
        """
        results: list[EpisodicEntry] = []
        for entry in self._entries.values():
            if tags and not all(t in (entry.tags or []) for t in tags):
                continue
            if query and query.lower() not in entry.content.lower():
                continue
            results.append(entry)

        # Sort most recent first, then by importance as tiebreaker
        results.sort(key=lambda e: (e.timestamp, e.importance), reverse=True)
        return results[:limit]

    def update(self, entry_id: str, **fields: object) -> EpisodicEntry | None:
        """Update mutable fields on an existing entry."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        for key, value in fields.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        self._save()
        return entry

    def prune(self, max_entries: int = 1000) -> int:
        """Remove the lowest-importance entries until below ``max_entries``.

        Parameters
        ----------
        max_entries : int
            Target maximum size. Entries below the importance threshold
            are removed oldest-first within their importance band.

        Returns
        -------
        int
            Number of entries removed.
        """
        if len(self._entries) <= max_entries:
            return 0

        # Sort by (importance asc, timestamp asc) – drop lowest importance first
        sorted_entries = sorted(
            self._entries.values(), key=lambda e: (e.importance, e.timestamp)
        )
        to_remove = len(self._entries) - max_entries
        removed = 0
        for entry in sorted_entries:
            if removed >= to_remove:
                break
            del self._entries[entry.id]
            removed += 1

        self._save()
        return removed

    def delete(self, entry_id: str) -> bool:
        """Remove a specific entry by id. Returns True if it existed."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def stats(self) -> dict:
        """Return summary statistics for the store."""
        if not self._entries:
            return {"total": 0, "avg_importance": 0.0, "by_tag": {}}
        total = len(self._entries)
        avg_imp = sum(e.importance for e in self._entries.values()) / total
        by_tag: dict[str, int] = {}
        for entry in self._entries.values():
            for tag in entry.tags or []:
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return {"total": total, "avg_importance": avg_imp, "by_tag": by_tag}

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()
        self._save()
