"""Self-reflection analyzer - learn from mistakes and successes.

The analyzer performs a real LLM-based reflection over a conversation
(via Ollama) to produce structured "what went well / what went wrong"
insights. When the LLM is unavailable or fails, it falls back to a
deterministic, content-based heuristic that still extracts concrete
observations from the conversation text (not just metadata).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


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
    # Which path produced this report: "llm" | "fallback"
    source: str = "fallback"


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

# Canonical category names the LLM is allowed to emit
VALID_CATEGORIES: frozenset[str] = frozenset(CATEGORY_PATTERNS) | frozenset({"general"})
VALID_SEVERITIES = ("info", "warning", "critical")


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


def _sanitize_category(value: object) -> str:
    """Normalize a category value to one of the known categories."""
    if isinstance(value, str):
        normalized = value.strip().lower().replace(" ", "-").replace("_", "-")
        if normalized in VALID_CATEGORIES:
            return normalized
    return "general"


def _sanitize_severity(value: object) -> str:
    """Normalize a severity value to one of the known severities."""
    if isinstance(value, str) and value.strip().lower() in VALID_SEVERITIES:
        return value.strip().lower()
    return "info"


# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_REFLECT_SYSTEM_PROMPT = """You are a self-reflection analyst for an AI agent. Given a conversation, analyze what happened and extract actionable lessons.

Output a JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "went_well": ["short factual statement of what worked well"],
  "went_wrong": ["short factual statement of what went wrong or caused problems"],
  "missing_info": ["information that was missing or had to be guessed"],
  "lessons": [
    {
      "category": "tool-use" | "context-management" | "task-planning" | "communication" | "security" | "general",
      "observation": "what was observed in the conversation (max 200 chars)",
      "lesson_text": "an actionable lesson the agent should remember (max 300 chars)",
      "severity": "info" | "warning" | "critical"
    }
  ]
}

Rules:
- Base every statement ONLY on the conversation content; never invent events.
- Be specific: quote concrete errors, names, values, or steps when present.
- "went_well" and "went_wrong" are the core answer: what actually went well / wrong in this session.
- Use at most 5 items per list and at most 5 lessons.
- Severity "critical" only for data loss, security issues, or destructive failures.
- Return valid JSON only."""

_REFLECT_USER_PROMPT = """Reflect on this conversation and extract lessons.

Conversation:
---
{conversation}
---"""


def _render_conversation(conversation: list[dict], max_chars: int = 12000) -> str:
    """Render a conversation to compact text for the LLM prompt."""
    lines = []
    total = 0
    for msg in conversation:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "unknown"))
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        line = f"[{role}] {content[:500]}"
        if total + len(line) > max_chars:
            lines.append("... (truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


class ReflectionAnalyzer:
    """Analyzes interactions to extract lessons and track improvement.

    After each significant interaction, runs a real LLM-based reflection
    (Ollama) over the conversation content to identify what went well,
    what failed, and what information was missing. Falls back to a
    content-based heuristic when the LLM is unavailable.

    Parameters
    ----------
    semantic_memory :
        Optional semantic memory backend (used by ``record_success``).
    storage_path :
        Where lessons are persisted (JSON). Defaults to the
        ``REFLECTION_STORAGE`` env var or ``data/lessons.json``.
    llm_model :
        Ollama model name. Defaults to the ``OLLAMA_MODEL`` env var
        (same convention as the rest of the engine), else "qwen3.5-9b".
    llm_base_url :
        Ollama base URL. Defaults to the ``OLLAMA_BASE_URL`` env var,
        else ``http://localhost:11434``.
    llm_timeout :
        Per-call timeout in seconds.
    fallback_top_n :
        Number of most important messages the fallback summarizes.
    """

    DEFAULT_MODEL = "qwen3.5-9b"

    def __init__(
        self,
        semantic_memory=None,
        storage_path: str | None = None,
        llm_model: str | None = None,
        llm_base_url: str | None = None,
        llm_timeout: float = 60.0,
        fallback_top_n: int = 3,
    ):
        self.semantic_memory = semantic_memory
        self.llm_model = llm_model or os.environ.get("OLLAMA_MODEL") or self.DEFAULT_MODEL
        self.llm_base_url = (
            llm_base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
        )
        self.llm_timeout = llm_timeout
        self.fallback_top_n = max(1, int(fallback_top_n))
        self._lessons: dict[str, Lesson] = {}
        self._mistake_counts: dict[str, int] = {}
        self.storage_path = storage_path or os.environ.get(
            "REFLECTION_STORAGE", "data/lessons.json"
        )
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist active lessons to disk."""
        active = [lesson for lesson in self._lessons.values() if not lesson.resolved]
        data = {
            "lessons": [asdict(lesson) for lesson in active],
            "mistake_counts": self._mistake_counts,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.storage_path == ":memory:":
            return  # ":memory:" is used by tests to avoid disk writes
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def load(self) -> None:
        """Load lessons from disk if available."""
        if self.storage_path == ":memory:" or not os.path.exists(self.storage_path):
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

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(self, interaction_id: str, conversation: list[dict]) -> ReflectionReport:
        """Analyze an interaction and generate a reflection report.

        Tries a real LLM call (Ollama) over the conversation content and
        parses the structured response. If the LLM is unavailable, fails,
        or returns an unparseable result, falls back to a deterministic
        content-based analysis of the most important messages.
        """
        messages = [m for m in conversation if isinstance(m, dict)]
        if not messages:
            return ReflectionReport(interaction_id=interaction_id, source="fallback")

        # 1) Try the LLM path (real content analysis)
        try:
            result = self._reflect_with_llm(messages)
        except Exception as exc:  # network, model, import errors
            logger.warning("LLM reflection failed, using fallback: %s", exc)
            result = None

        if result is not None:
            report = ReflectionReport(
                interaction_id=interaction_id,
                went_well=result["went_well"],
                went_wrong=result["went_wrong"],
                missing_info=result["missing_info"],
                lessons=result["lessons"],
                source="llm",
            )
        else:
            # 2) Content-based fallback: summarize the most important N
            #    messages and derive structured lessons from them.
            report = self._analyze_fallback(interaction_id, messages)

        # Track lessons and mistake frequency (identical for both paths,
        # so downstream behavior is backward compatible)
        for lesson in report.lessons:
            self._add_lesson(lesson)
            self._mistake_counts[lesson.category] = self._mistake_counts.get(lesson.category, 0) + 1

        return report

    # -- LLM path ------------------------------------------------------

    def _reflect_with_llm(self, messages: list[dict]) -> dict | None:
        """Call Ollama to reflect on the conversation. Returns parsed dict
        or None when unavailable/failed/unparseable."""
        try:
            import ollama
        except ImportError:
            logger.debug("ollama package not available, using reflection fallback")
            return None

        if not hasattr(ollama, "Client"):
            # Module stub without a real client (e.g. partial import in tests)
            logger.debug("ollama module has no Client, using reflection fallback")
            return None

        rendered = _render_conversation(messages)
        if not rendered:
            return None

        try:
            client = ollama.Client(host=self.llm_base_url, timeout=self.llm_timeout)
            response = client.chat(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": _REFLECT_SYSTEM_PROMPT},
                    {"role": "user", "content": _REFLECT_USER_PROMPT.format(conversation=rendered)},
                ],
                options={"temperature": 0.2, "num_predict": 1024},
            )
            content = (response.message.content or "").strip()
        except Exception as exc:  # pragma: no cover — network, model errors
            logger.warning("Ollama reflection call failed: %s", exc)
            return None

        return self._parse_reflection_json(content)

    @staticmethod
    def _parse_reflection_json(content: str) -> dict | None:
        """Parse and validate the LLM JSON output. Returns None on any
        structural problem so the caller can fall back."""
        if not content:
            return None
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content.rsplit("\n", 1)[0]
        content = content.strip()

        # Extract the first JSON object if the model added prose around it
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            data = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            logger.debug("reflection LLM returned invalid JSON")
            return None

        if not isinstance(data, dict):
            return None

        def _str_list(key: str, cap: int = 5) -> list[str]:
            raw = data.get(key)
            if not isinstance(raw, list):
                return []
            return [str(item).strip() for item in raw if str(item).strip()][:cap]

        lessons: list[Lesson] = []
        raw_lessons = data.get("lessons")
        if isinstance(raw_lessons, list):
            for item in raw_lessons[:5]:
                if not isinstance(item, dict):
                    continue
                observation = str(item.get("observation", "")).strip()[:200]
                lesson_text = str(item.get("lesson_text", "")).strip()[:300]
                if not observation and not lesson_text:
                    continue
                category = _sanitize_category(item.get("category"))
                severity = _sanitize_severity(item.get("severity"))
                if severity == "info" and lesson_text:
                    # Let the heuristic refine info-level severity from text
                    severity = extract_severity(f"{observation} {lesson_text}")
                lessons.append(
                    Lesson(
                        id=f"lesson_llm_{len(lessons)}",
                        category=category,
                        observation=observation,
                        lesson_text=lesson_text,
                        severity=severity,
                    )
                )

        return {
            "went_well": _str_list("went_well"),
            "went_wrong": _str_list("went_wrong"),
            "missing_info": _str_list("missing_info"),
            "lessons": lessons,
        }

    # -- Fallback path ---------------------------------------------------

    _SUCCESS_KEYWORDS = [
        "success",
        "successfully",
        "works",
        "worked",
        "solved",
        "fixed",
        "resolved",
        "completed",
        "great",
        "done",
    ]
    _FAILURE_KEYWORDS = [
        "error",
        "failed",
        "failure",
        "wrong",
        "bug",
        "issue",
        "problem",
        "exception",
        "timeout",
        "crash",
        "broke",
        "broken",
        "rejected",
        "denied",
        "invalid",
        "mismatch",
        "conflict",
    ]
    _MISSING_KEYWORDS = ["didn't know", "i don't know", "missing", "unclear", "unknown", "assumed"]

    def _message_importance(self, content: str) -> int:
        """Score a message's importance for the fallback summary."""
        lowered = content.lower()
        score = sum(1 for kw in self._FAILURE_KEYWORDS if kw in lowered) * 2
        score += sum(1 for kw in self._MISSING_KEYWORDS if kw in lowered)
        score += sum(1 for kw in self._SUCCESS_KEYWORDS if kw in lowered)
        # Concrete evidence (code, paths, URLs, error output) is high-signal
        score += 1 if re.search(r"[\w/]+\.(py|js|ts|json|yml|yaml|sh|log)", content) else 0
        score += 1 if re.search(r"\b(traceback|stack trace|error:)\b", lowered) else 0
        return score

    def _analyze_fallback(self, interaction_id: str, messages: list[dict]) -> ReflectionReport:
        """Deterministic, content-based analysis.

        Summarizes the N most important messages (by content signals, not
        just metadata) and derives structured lessons from them.
        """
        went_well: list[str] = []
        went_wrong: list[str] = []
        missing_info: list[str] = []

        for msg in messages:
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            lowered = content.lower()

            if any(kw in lowered for kw in self._SUCCESS_KEYWORDS):
                went_well.append(content[:200])
            if any(kw in lowered for kw in self._FAILURE_KEYWORDS):
                went_wrong.append(content[:200])
            if any(kw in lowered for kw in self._MISSING_KEYWORDS):
                missing_info.append(content[:200])

        # Most important N messages form the basis of the fallback summary
        ranked = sorted(
            (
                str(m.get("content", "")).strip()
                for m in messages
                if str(m.get("content", "")).strip()
            ),
            key=lambda c: -self._message_importance(c),
        )
        top_messages = ranked[: self.fallback_top_n]

        lessons: list[Lesson] = []
        seen: set[str] = set()
        # Priority order: failures first (lessons are about problems),
        # then missing info, then notable successes.
        pools = [
            (went_wrong, "went_wrong"),
            (missing_info, "missing_info"),
            (went_well, "went_well"),
        ]
        for pool, pool_name in pools:
            for item in pool:
                if len(lessons) >= max(len(top_messages), 3):
                    break
                key = item[:80].lower()
                if key in seen:
                    continue
                seen.add(key)
                categories = detect_category(item)
                severity = extract_severity(item)
                if pool_name == "went_well":
                    severity = "info"
                lessons.append(
                    Lesson(
                        id=f"lesson_{len(lessons)}",
                        category=categories[0],
                        observation=item[:100],
                        lesson_text=self._generate_lesson_text(item, categories[0], pool_name),
                        severity=severity,
                    )
                )
        # If nothing matched keywords but messages exist, summarize the top
        # messages so the report is still content-based (not empty metadata)
        if not lessons and top_messages:
            for item in top_messages:
                categories = detect_category(item)
                lessons.append(
                    Lesson(
                        id=f"lesson_{len(lessons)}",
                        category=categories[0],
                        observation=item[:100],
                        lesson_text=f"Notable exchange to review: {item[:80]}",
                        severity="info",
                    )
                )

        # Cap the summary lists, but always include the top-N message
        # summaries in the report's went_wrong/went_well context
        def _cap(items: list[str], extra: list[str]) -> list[str]:
            merged = list(items)
            for extra_item in extra:
                if extra_item not in merged:
                    merged.append(extra_item)
            return merged[:5]

        top_wrong = [c for c in top_messages if any(k in c.lower() for k in self._FAILURE_KEYWORDS)]
        top_well = [c for c in top_messages if any(k in c.lower() for k in self._SUCCESS_KEYWORDS)]

        return ReflectionReport(
            interaction_id=interaction_id,
            went_well=_cap(went_well, top_well),
            went_wrong=_cap(went_wrong, top_wrong),
            missing_info=missing_info[:5],
            lessons=lessons,
            source="fallback",
        )

    def _generate_lesson_text(self, observation: str, category: str, pool_name: str) -> str:
        """Generate a lesson text from observation."""
        if pool_name == "went_well":
            return f"Keep doing what worked: {observation[:80]}"
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

    # ------------------------------------------------------------------
    # Consultation & tracking (consumers of the lessons)
    # ------------------------------------------------------------------

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
