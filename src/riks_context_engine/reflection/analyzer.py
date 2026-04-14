"""Self-reflection analyzer - learn from mistakes and successes."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Lesson:
    """A learned lesson from reflection."""

    id: str
    category: str  # e.g., "tool-use", "context-management", "task-planning"
    observation: str
    lesson_text: str
    severity: str  # "info" | "warning" | "critical"
    occurrence_count: int = 1
    first_seen: datetime = datetime.now(timezone.utc)
    last_seen: datetime = datetime.now(timezone.utc)
    resolved: bool = False


@dataclass
class ReflectionReport:
    """Post-interaction reflection report."""

    interaction_id: str
    went_well: list[str]
    went_wrong: list[str]
    missing_info: list[str]
    lessons: list[Lesson]
    timestamp: datetime = datetime.now(timezone.utc)


class ReflectionAnalyzer:
    """Analyzes interactions to extract lessons and track improvement.

    After each significant interaction, runs a lightweight self-check
    to identify what went well, what failed, and what information
    was missing.
    """

    def __init__(self, semantic_memory: object | None = None) -> None:
        self.semantic_memory = semantic_memory

    def analyze(self, interaction_id: str, conversation: list[dict]) -> ReflectionReport:
        """Analyze an interaction and generate a reflection report."""
        report = ReflectionReport(
            interaction_id=interaction_id,
            went_well=[],
            went_wrong=[],
            missing_info=[],
            lessons=[],
        )
        return report

    def consult_before_task(self, task_description: str) -> list[Lesson]:
        """Before starting a task, check for related past lessons."""
        return []

    def record_success(self, task_id: str, details: str) -> None:
        """Record a successful task completion."""
        pass

    def record_failure(self, task_id: str, error: str, root_cause: str | None = None) -> None:
        """Record a failed task."""
        pass

    def track_mistake_frequency(self) -> dict[str, int]:
        """Track how often each category of mistake occurs."""
        return {}
