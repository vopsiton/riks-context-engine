"""Procedural memory - skills, workflows, how-to knowledge."""

import json
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
    success_rate: float = 1.0  # 0.0 - 1.0
    tags: list[str] = field(default_factory=list)


class ProceduralMemory:
    """Stores skills, workflows, and how-to knowledge.

    Captures how to perform tasks so they can be recalled
    and reused without relearning.
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path or "data/procedural.json"
        self._procedures: dict[str, Procedure] = {}
        self._load()

    def _load(self) -> None:
        """Load procedures from disk."""
        path = Path(self.storage_path)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for d in data.values():
                    created = d["created_at"]
                    if isinstance(created, str):
                        created = datetime.fromisoformat(created)
                    last_used = d["last_used"]
                    if isinstance(last_used, str):
                        last_used = datetime.fromisoformat(last_used)
                    self._procedures[d["id"]] = Procedure(
                        id=d["id"],
                        name=d["name"],
                        description=d["description"],
                        steps=d.get("steps", []),
                        created_at=created,
                        last_used=last_used,
                        use_count=d.get("use_count", 0),
                        success_rate=d.get("success_rate", 1.0),
                        tags=d.get("tags", []),
                    )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

    def _save(self) -> None:
        """Persist procedures to disk."""
        Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        data = {
            pid: {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "steps": p.steps,
                "created_at": p.created_at.isoformat(),
                "last_used": p.last_used.isoformat(),
                "use_count": p.use_count,
                "success_rate": p.success_rate,
                "tags": p.tags,
            }
            for pid, p in self._procedures.items()
        }
        Path(self.storage_path).write_text(json.dumps(data, indent=2))

    def store(
        self,
        name: str,
        description: str,
        steps: list[str],
        tags: list[str] | None = None,
    ) -> Procedure:
        """Store a new procedure."""
        now = datetime.now(timezone.utc)
        proc = Procedure(
            id=f"pr_{now.timestamp()}",
            name=name,
            description=description,
            steps=steps,
            created_at=now,
            last_used=now,
            tags=tags or [],
        )
        self._procedures[proc.id] = proc
        self._save()
        return proc

    def get(self, proc_id: str) -> Procedure | None:
        """Get a procedure by ID, updating use stats."""
        proc = self._procedures.get(proc_id)
        if proc:
            proc.use_count += 1
            proc.last_used = datetime.now(timezone.utc)
            self._save()
        return proc

    def recall(self, name: str) -> Procedure | None:
        """Recall a procedure by exact name match."""
        for proc in self._procedures.values():
            if proc.name.lower() == name.lower():
                proc.use_count += 1
                proc.last_used = datetime.now(timezone.utc)
                self._save()
                return proc
        return None

    def find(self, query: str) -> list[Procedure]:
        """Find procedures matching a query string."""
        q = query.lower()
        matches = [
            p for p in self._procedures.values()
            if (q in p.name.lower() or
                q in p.description.lower() or
                any(q in (t or "") for t in p.tags))
        ]
        matches.sort(key=lambda p: (p.use_count, p.success_rate), reverse=True)
        return matches

    def delete(self, proc_id: str) -> bool:
        """Delete a procedure by ID."""
        if proc_id in self._procedures:
            del self._procedures[proc_id]
            self._save()
            return True
        return False

    def update_success_rate(self, proc_id: str, success: bool) -> bool:
        """Update success rate for a procedure after execution."""
        proc = self._procedures.get(proc_id)
        if not proc:
            return False
        n = proc.use_count
        proc.success_rate = (proc.success_rate * (n - 1) + (1.0 if success else 0.0)) / n
        self._save()
        return True

    @property
    def procedures(self) -> dict[str, Procedure]:
        return self._procedures

    def __len__(self) -> int:
        return len(self._procedures)
