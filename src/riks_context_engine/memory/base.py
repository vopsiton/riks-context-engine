"""Shared MemoryEntry schema for the 3-tier memory system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MemoryType(Enum):
    """Discriminator for the three memory tiers."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class MemoryEntry:
    """Unified schema for all memory entries.

    Attributes
    ----------
    id : str
        Unique identifier prefixed by tier (e.g. ``ep_123``).
    type : MemoryType
        Which tier this entry belongs to.
    content : str
        Human-readable content (the "fact" or "observation").
    timestamp : datetime
        When this entry was created (UTC).
    importance : float
        Significance score in [0.0, 1.0]. Higher values are kept longer.
    embedding : list[float] | None
        Vector representation for semantic search. Generated on-demand
        for episodic/procedural; stored for semantic.
    access_count : int
        Number of times this entry has been retrieved.
    last_accessed : datetime | None
        UTC timestamp of most recent retrieval.
    metadata : dict[str, Any]
        Tier-specific extra fields.
    """

    id: str
    type: MemoryType
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    importance: float = 0.5
    embedding: list[float] | None = None
    access_count: int = 0
    last_accessed: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_access(self) -> None:
        """Increment access counter and update last_accessed."""
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "importance": self.importance,
            "embedding": self.embedding,
            "access_count": self.access_count,
            "last_accessed": (
                self.last_accessed.isoformat() if self.last_accessed else None
            ),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """Reconstruct a MemoryEntry from a dictionary."""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        last_accessed = data.get("last_accessed")
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
        return cls(
            id=data["id"],
            type=MemoryType(data["type"]),
            content=data["content"],
            timestamp=timestamp,
            importance=data.get("importance", 0.5),
            embedding=data.get("embedding"),
            access_count=data.get("access_count", 0),
            last_accessed=last_accessed,
            metadata=data.get("metadata", {}),
        )
