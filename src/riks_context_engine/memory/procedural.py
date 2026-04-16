"""Procedural memory - skills, workflows, how-to knowledge."""

from __future__ import annotations

import json
from dataclasses import dataclass
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


class ProceduralMemory:
    """Stores skills, workflows, and how-to knowledge.

    Captures how to perform tasks so they can be recalled
    and reused without relearning.
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path or "data/procedural.json"
        self._procedures: dict[str, Procedure] = {}
        if storage_path != ":memory:":
            Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        """Load procedures from JSON file."""
        if self.storage_path == ":memory:":
            return
        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            for item in data:
                proc = Procedure(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    steps=item["steps"],
                    created_at=datetime.fromisoformat(item["created_at"]),
                    last_used=datetime.fromisoformat(item["last_used"]),
                    use_count=item.get("use_count", 0),
                    success_rate=item.get("success_rate", 1.0),
                )
                self._procedures[proc.id] = proc
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # Empty store on first run

    def _persist(self) -> None:
        """Write procedures to JSON file."""
        if self.storage_path == ":memory:":
            return
        data = []
        for proc in self._procedures.values():
            data.append(
                {
                    "id": proc.id,
                    "name": proc.name,
                    "description": proc.description,
                    "steps": proc.steps,
                    "created_at": proc.created_at.isoformat(),
                    "last_used": proc.last_used.isoformat(),
                    "use_count": proc.use_count,
                    "success_rate": proc.success_rate,
                }
            )
        with open(self.storage_path, "w") as f:
            json.dump(data, f)

    def store(self, name: str, description: str, steps: list[str]) -> Procedure:
        """Store a new procedure."""
        now = datetime.now(timezone.utc)
        proc = Procedure(
            id=f"pr_{now.timestamp()}",
            name=name,
            description=description,
            steps=steps,
            created_at=now,
            last_used=now,
        )
        self._procedures[proc.id] = proc
        self._persist()
        return proc

    def get(self, proc_id: str) -> Procedure | None:
        """Get a procedure by ID."""
        return self._procedures.get(proc_id)

    def recall(self, name: str) -> Procedure | None:
        """Recall a procedure by exact name match."""
        for proc in self._procedures.values():
            if proc.name.lower() == name.lower():
                proc.use_count += 1
                proc.last_used = datetime.now(timezone.utc)
                self._persist()
                return proc
        return None

    def find(self, query: str) -> list[Procedure]:
        """Find procedures matching a query (substring in name or description)."""
        query_lower = query.lower()
        results = []
        for proc in self._procedures.values():
            if query_lower in proc.name.lower() or query_lower in proc.description.lower():
                results.append(proc)
        return results
