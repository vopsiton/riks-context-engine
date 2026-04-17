"""Episodic memory - session-level, short-term observations."""

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
    access_count: int = 0
    last_accessed: datetime | None = None


class EpisodicMemory:
    """Session-level, short-term memory store.

    Stores recent observations, conversation snippets, and
    ephemeral facts that don't persist across sessions.
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path or "data/episodic.json"
        self._entries: dict[str, EpisodicEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load entries from disk if available."""
        path = Path(self.storage_path)
        if path.exists():
            import json

            try:
                data = json.loads(path.read_text())
                for d in data.values():
                    ts = d["timestamp"]
                    if isinstance(ts, str):
                        ts = datetime.fromisoformat(ts)
                    self._entries[d["id"]] = EpisodicEntry(
                        id=d["id"],
                        timestamp=ts,
                        content=d["content"],
                        importance=d.get("importance", 0.5),
                        embedding=d.get("embedding"),
                        tags=d.get("tags"),
                    )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # Start fresh on corruption

    def _save(self) -> None:
        """Persist entries to disk."""
        Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        import json

        data = {
            eid: {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "content": e.content,
                "importance": e.importance,
                "embedding": e.embedding,
                "tags": e.tags,
            }
            for eid, e in self._entries.items()
        }
        Path(self.storage_path).write_text(json.dumps(data, indent=2))

    def add(
        self,
        content: str,
        importance: float = 0.5,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> EpisodicEntry:
        """Add an episodic memory entry."""
        now = datetime.now(timezone.utc)
        entry = EpisodicEntry(
            id=f"ep_{now.timestamp()}",
            timestamp=now,
            content=content,
            importance=importance,
            tags=tags or [],
            embedding=embedding,
        )
        self._entries[entry.id] = entry
        self._save()
        return entry

    def get(self, entry_id: str) -> EpisodicEntry | None:
        """Get a single entry by ID, incrementing access count."""
        entry = self._entries.get(entry_id)
        if entry:
            entry.access_count += 1  # type: ignore[attr-defined]
            entry.last_accessed = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        return entry

    @property
    def entries(self) -> dict[str, EpisodicEntry]:
        return self._entries

    def query(self, query: str, limit: int = 10) -> list[EpisodicEntry]:
        """Query episodic memory by keyword match."""
        q = query.lower()
        matches = [
            e
            for e in self._entries.values()
            if q in e.content.lower() or any(q in (t or "") for t in (e.tags or []))
        ]
        # Sort by importance desc, then timestamp desc
        matches.sort(key=lambda e: (e.importance, e.timestamp.timestamp()), reverse=True)
        return matches[:limit]

    def prune(self, max_entries: int = 1000) -> int:
        """Remove low-importance entries when limit is exceeded."""
        if len(self._entries) <= max_entries:
            return 0
        # Sort by (importance asc, timestamp asc) - prune least important first
        sorted_entries = sorted(
            self._entries.items(),
            key=lambda kv: (kv[1].importance, kv[1].timestamp.timestamp()),
        )
        removed = 0
        while len(self._entries) > max_entries and sorted_entries:
            entry_id, _ = sorted_entries.pop(0)
            del self._entries[entry_id]
            removed += 1
        if removed:
            self._save()
        return removed

    def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def __len__(self) -> int:
        return len(self._entries)
