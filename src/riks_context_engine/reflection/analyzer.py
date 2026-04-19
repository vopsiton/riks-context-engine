"""Self-reflection analyzer - learn from mistakes and successes."""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Lesson:
    """A learned lesson from reflection."""

    id: str
    category: str  # e.g., "tool-use", "context-management", "task-planning"
    observation: str
    lesson_text: str
    severity: str = "info"  # "info" | "warning" | "critical"
    occurrence_count: int = 1
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False


@dataclass
class ReflectionReport:
    """Post-interaction reflection report."""

    interaction_id: str
    went_well: list[str] = field(default_factory=list)
    went_wrong: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    lessons: list[Lesson] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Category detection patterns
CATEGORY_PATTERNS = {
    "tool-use": [
        r"tool.*fail",
        r"function.*error",
        r"api.*",
        r"missing.*parameter",
        r"invalid.*argument",
        r"permission.*denied",
    ],
    "context-management": [
        r"context.*overflow",
        r"token.*limit",
        r"memory.*full",
        r"forgot.*prefer",
        r"lost.*track",
        r"prune.*error",
    ],
    "task-planning": [
        r"wrong.*order",
        r"missed.*step",
        r"assumed.*wrong",
        r"dependency.*broken",
        r"unexpected.*blocker",
        r"incomplete.*goal",
    ],
    "communication": [
        r"unclear.*request",
        r"misunderstood.*intent",
        r"gave.*wrong.*info",
        r"confusing.*response",
    ],
    "security": [
        r"injection",
        r"exposure",
        r"unauthorized",
        r"data.*leak",
        r"credential.*exposed",
        r"validation.*fail",
        r"vulnerability",
    ],
}


def detect_category(text: str) -> list[str]:
    """Detect categories from text using pattern matching."""
    text_lower = text.lower()
    detected = []
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                detected.append(category)
                break
    return detected if detected else ["general"]


def extract_severity(text: str) -> str:
    """Extract severity level from text indicators."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["critical", "disaster", "security", "breach", "data loss"]):
        return "critical"
    if any(k in text_lower for k in ["warning", "careful", "mistake", "wrong", "failed"]):
        return "warning"
    return "info"


class ReflectionAnalyzer:
    """Analyzes interactions to extract lessons and track improvement.

    After each significant interaction, runs a lightweight self-check
    to identify what went well, what failed, and what information
    was missing.
    """

    def __init__(self, semantic_memory=None, storage_path: str | None = None):  # type: ignore[no-untyped-def]
        self.semantic_memory = semantic_memory
        self._lessons: dict[str, Lesson] = {}
        self._mistake_counts: dict[str, int] = {}
        self.storage_path = storage_path or os.environ.get(
            "REFLECTION_STORAGE", "data/lessons.json"
        )
        self.load()

    def save(self) -> None:
        """Persist active lessons to disk."""
        active = [l for l in self._lessons.values() if not l.resolved]
        data = {
            "lessons": [asdict(l) for l in active],
            "mistake_counts": self._mistake_counts,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


    def load(self) -> None:
        """Load lessons from disk if available."""
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            for l_dict in data.get("lessons", []):
                # Convert datetime strings back
                for dt_field in ("first_seen", "last_seen"):
                    if isinstance(l_dict.get(dt_field), str):
                        l_dict[dt_field] = datetime.fromisoformat(l_dict[dt_field])
                lesson = Lesson(**l_dict)
                self._lessons[lesson.id] = lesson
            self._mistake_counts = data.get("mistake_counts", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Ignore corrupt files

    def analyze(self, interaction_id: str, conversation: list[dict]) -> ReflectionReport:
        """Analyze an interaction and generate a reflection report."""
        went_well = []
        went_wrong = []
        missing_info = []

        # Simple pattern-based analysis
        for msg in conversation:
            content = msg.get("content", "")
            _role = msg.get("role", "")

            # Look for success indicators
            if any(
                kw in content.lower() for kw in ["success", "works", "solved", "fixed", "great"]
            ):
                went_well.append(content[:200])

            # Look for failure indicators
            has_error = any(
                kw in content.lower()
                for kw in ["error", "fail", "wrong", "bug", "issue", "problem"]
            )
            has_api = any(
                kw in content.lower() for kw in ["timeout", "api", "http", "request", "endpoint"]
            )

            if has_error or has_api:
                went_wrong.append(content[:200])

            # Look for missing info patterns
            if (
                "didn't know" in content.lower()
                or "missing" in content.lower()
                or "unclear" in content.lower()
            ):
                missing_info.append(content[:200])

        # Extract lessons from what went wrong
        lessons = []
        for wrong in went_wrong:
            categories = detect_category(wrong)
            severity = extract_severity(wrong)

            lesson_id = f"lesson_{len(self._lessons)}"
            lesson = Lesson(
                id=lesson_id,
                category=categories[0],
                observation=wrong[:100],
                lesson_text=self._generate_lesson_text(wrong, categories[0]),
                severity=severity,
            )
            lessons.append(lesson)
            self._add_lesson(lesson)

        # Update mistake tracking
        for lesson in lessons:
            self._mistake_counts[lesson.category] = self._mistake_counts.get(lesson.category, 0) + 1

        report = ReflectionReport(
            interaction_id=interaction_id,
            went_well=went_well[:5],  # Cap at 5
            went_wrong=went_wrong[:5],
            missing_info=missing_info[:5],
            lessons=lessons,
        )
        return report

    def _generate_lesson_text(self, observation: str, category: str) -> str:
        """Generate a lesson text from observation."""
        # Simple template-based generation
        templates = {
            "tool-use": f"Check tool parameters and error handling when encountering: {observation[:50]}",
            "context-management": f"Monitor context limits and preserve important info: {observation[:50]}",
            "task-planning": f"Verify task structure and dependencies before execution: {observation[:50]}",
            "communication": f"Clarify requirements before assuming: {observation[:50]}",
            "security": f"SECURITY: Validate all inputs and handle errors safely: {observation[:50]}",
            "general": f"Consider: {observation[:50]}",
        }
        return templates.get(category, templates["general"])

    def _add_lesson(self, lesson: Lesson) -> None:
        """Add lesson, merging with existing similar lessons."""
        # Check for similar existing lesson
        for existing in self._lessons.values():
            if existing.category == lesson.category and existing.severity == lesson.severity:
                existing.occurrence_count += 1
                existing.last_seen = datetime.now(timezone.utc)
                return
        self._lessons[lesson.id] = lesson
        self.save()

    def consult_before_task(self, task_description: str) -> list[Lesson]:
        """Before starting a task, check for related past lessons."""
        task_categories = detect_category(task_description)
        relevant = []

        for lesson in self._lessons.values():
            if lesson.category in task_categories and not lesson.resolved:
                if lesson.severity in ("critical", "warning"):
                    relevant.append(lesson)

        return relevant[:5]  # Return top 5

    def record_success(self, task_id: str, details: str) -> None:
        """Record a successful task completion."""
        # Store in memory if available
        if self.semantic_memory:
            self.semantic_memory.store(
                key=f"success:{task_id}",
                value={
                    "task_id": task_id,
                    "details": details,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

    def record_failure(self, task_id: str, error: str, root_cause: str | None = None) -> None:
        """Record a failed task."""
        categories = detect_category(error)
        severity = extract_severity(error)

        lesson_id = f"lesson_failure_{task_id}"
        lesson = Lesson(
            id=lesson_id,
            category=categories[0],
            observation=error[:100],
            lesson_text=f"Task {task_id} failed: {error[:80]}. Root cause: {root_cause or 'unknown'}",
            severity=severity,
        )
        self._add_lesson(lesson)
        self._mistake_counts[lesson.category] = self._mistake_counts.get(lesson.category, 0) + 1

    def track_mistake_frequency(self) -> dict[str, int]:
        """Track how often each category of mistake occurs."""
        return dict(self._mistake_counts)

    def get_active_lessons(self) -> list[Lesson]:
        """Get all unresolved lessons."""
        return [item for item in self._lessons.values() if not item.resolved]

    def resolve_lesson(self, lesson_id: str) -> bool:
        """Mark a lesson as resolved."""
        if lesson_id in self._lessons:
            self._lessons[lesson_id].resolved = True
            return True
        return False
