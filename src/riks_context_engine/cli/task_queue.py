"""CLI task queue — durable task entries (JSON-backed).

`riks task <goal>` (turn 2 of #124) adds a task to the queue in a real
store. `--execute` does NOT execute this turn (next turn implements real
execution after the task model is clarified); it prints an honest message.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def task_queue_path() -> str:
    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    base = os.path.join(data_dir, os.environ.get("RIKS_TASKS_FILE", "tasks.json"))
    tenant = os.environ.get("RIKS_TENANT_ID", "").strip()
    if tenant:
        base = os.path.join(data_dir, "tenants", tenant, "tasks.json")
    return base


@dataclass
class QueueTask:
    id: str
    goal: str
    status: str = "queued"  # queued | running | done | failed | timeout
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    executed_at: str | None = None
    result: str | None = None
    owner_tenant: str | None = None  # tenant that created the task (RIKS_TENANT_ID)


class TaskQueue:
    """Append-only JSON task queue, tenant-scoped like the memory stores."""

    def __init__(self, path: str | None = None):
        self.path = path or task_queue_path()
        self._tasks: dict[str, QueueTask] = {}
        self._load()

    def _load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text())
            for d in data.get("tasks", []):
                t = QueueTask(**d)
                self._tasks[t.id] = t
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass  # start fresh on corruption

    def _save(self) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"tasks": [asdict(t) for t in self._tasks.values()]}, indent=2))

    def add(self, goal: str) -> QueueTask:
        task = QueueTask(
            id=f"task_{uuid.uuid4().hex[:8]}",
            goal=goal,
            owner_tenant=os.environ.get("RIKS_TENANT_ID", "").strip() or None,
        )
        self._tasks[task.id] = task
        self._save()
        return task

    def list(self) -> list[QueueTask]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at)

    def get(self, task_id: str) -> QueueTask | None:
        return self._tasks.get(task_id)

    def mark(self, task_id: str, status: str, result: str | None = None) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        task.status = status
        if result is not None:
            task.result = result
        if status in ("done", "failed", "timeout"):
            task.executed_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def count(self, status: str | None = None) -> int:
        if status is None:
            return len(self._tasks)
        return sum(1 for t in self._tasks.values() if t.status == status)

    def to_dict(self) -> dict[str, Any]:
        return {"tasks": [asdict(t) for t in self.list()]}
