"""Procedural memory - skills, workflows, how-to knowledge."""

from dataclasses import dataclass
from datetime import datetime, timezone


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
        return proc

    def recall(self, name: str) -> Procedure | None:
        """Recall a procedure by name."""
        return None

    def find(self, query: str) -> list[Procedure]:
        """Find procedures matching a query."""
        return []
