"""Procedural memory - skills, workflows, how-to knowledge."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Procedure:
    """A callable procedure / skill."""

    id: str
    name: str
    description: str
    steps: list[str]
    created_at: datetime
    last_used: datetime
    use_count: int = 0
    success_rate: float = 1.0  # 0.0 – 1.0
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.success_rate = max(0.0, min(1.0, float(self.success_rate)))
        self.use_count = max(0, int(self.use_count))

    def record_use(self, success: bool) -> None:
        """Update usage statistics after a run."""
        self.use_count += 1
        self.last_used = datetime.now(timezone.utc)
        prev = self.success_rate
        n = self.use_count
        self.success_rate = (prev * (n - 1) + (1.0 if success else 0.0)) / n

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": self.steps,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
            "use_count": self.use_count,
            "success_rate": self.success_rate,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Procedure:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            steps=data["steps"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=datetime.fromisoformat(data["last_used"]),
            use_count=data.get("use_count", 0),
            success_rate=data.get("success_rate", 1.0),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


class ProceduralMemory:
    """Stores skills, workflows, and how-to knowledge.

    Captures how to perform tasks so they can be recalled and reused
    without relearning. Backed by a JSON file.
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path or "data/procedural.json"
        self._procedures: dict[str, Procedure] = {}
        self._load()

    def _load(self) -> None:
        path = Path(self.storage_path)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._procedures = {d["id"]: Procedure.from_dict(d) for d in data}
            except (json.JSONDecodeError, KeyError, ValueError):
                self._procedures = {}

    def _save(self) -> None:
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in self._procedures.values()]
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json_bytes)
        finally:
            os.close(fd)

    def _generate_id(self) -> str:
        return f"pr_{uuid.uuid4().hex}"

    def store(
        self,
        name: str,
        description: str,
        steps: list[str],
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Procedure:
        """Store a new procedure."""
        now = datetime.now(timezone.utc)
        proc = Procedure(
            id=self._generate_id(),
            name=name,
            description=description,
            steps=steps,
            created_at=now,
            last_used=now,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._procedures[proc.id] = proc
        self._save()
        return proc

    def get(self, proc_id: str) -> Procedure | None:
        """Retrieve a procedure by id."""
        return self._procedures.get(proc_id)

    def recall(self, name: str) -> Procedure | None:
        """Recall a procedure by exact name match (case-insensitive)."""
        name_lower = name.lower()
        for proc in self._procedures.values():
            if proc.name.lower() == name_lower:
                return proc
        return None

    def find(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[Procedure]:
        """Find procedures matching a query and/or tags."""
        results: list[Procedure] = []
        for proc in self._procedures.values():
            if tags and not all(t in proc.tags for t in tags):
                continue
            if query:
                ql = query.lower()
                if ql not in proc.name.lower() and ql not in proc.description.lower():
                    continue
            results.append(proc)

        results.sort(key=lambda p: (p.success_rate, p.use_count), reverse=True)
        return results[:limit]

    def record_execution(self, proc_id: str, success: bool) -> bool:
        """Record the outcome of executing a procedure."""
        proc = self._procedures.get(proc_id)
        if proc is None:
            return False
        proc.record_use(success)
        self._save()
        return True

    def update(self, proc_id: str, **fields: object) -> Procedure | None:
        """Update mutable fields on an existing procedure."""
        proc = self._procedures.get(proc_id)
        if proc is None:
            return None
        for key, value in fields.items():
            if hasattr(proc, key):
                setattr(proc, key, value)
        self._save()
        return proc

    def delete(self, proc_id: str) -> bool:
        """Remove a procedure. Returns True if it existed."""
        if proc_id in self._procedures:
            del self._procedures[proc_id]
            self._save()
            return True
        return False

    def stats(self) -> dict:
        if not self._procedures:
            return {"total": 0, "avg_success_rate": 0.0, "by_tag": {}}
        total = len(self._procedures)
        avg_sr = sum(p.success_rate for p in self._procedures.values()) / total
        total_uses = sum(p.use_count for p in self._procedures.values())
        by_tag: dict[str, int] = {}
        for proc in self._procedures.values():
            for tag in proc.tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return {
            "total": total,
            "avg_success_rate": avg_sr,
            "total_uses": total_uses,
            "by_tag": by_tag,
        }

    def clear(self) -> None:
        """Remove all procedures."""
        self._procedures.clear()
        self._save()