"""Task decomposition - goal → executable steps."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskDependency(Enum):
    BLOCKING = "blocking"  # Must complete before dependents
    PARALLEL = "parallel"  # Can run concurrently


@dataclass
class Task:
    """A single decomposable task."""

    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    parallel_group: str | None = None  # Tasks in same group can run in parallel
    success_criteria: str | None = None
    rollback_steps: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0
    category: str = "General"  # Task category for LLM-based decomposition

    def mark_done(self) -> None:
        self.status = TaskStatus.DONE
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self) -> None:
        self.status = TaskStatus.FAILED

    def mark_running(self) -> None:
        self.status = TaskStatus.RUNNING

    def can_execute(self, completed_task_ids: set[str]) -> bool:
        """Check if all dependencies are satisfied."""
        return all(dep_id in completed_task_ids for dep_id in self.dependencies)


@dataclass
class TaskGraph:
    """A graph of decomposed tasks."""

    goal: str
    tasks: list[Task] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_task(self, task_id: str) -> Task | None:
        """Get task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def get_ready_tasks(self, completed: set[str]) -> list[Task]:
        """Get tasks that are ready to execute."""
        ready = []
        for task in self.tasks:
            if task.status == TaskStatus.PENDING and task.can_execute(completed):
                ready.append(task)
        return ready

    def get_parallel_groups(self) -> dict[str, list[Task]]:
        """Group tasks by parallel_group for concurrent execution."""
        groups: dict[str, list[Task]] = {}
        for task in self.tasks:
            if task.parallel_group:
                if task.parallel_group not in groups:
                    groups[task.parallel_group] = []
                groups[task.parallel_group].append(task)
        return groups


# Simple keyword-based decomposition patterns
DECOMPOSE_PATTERNS = [
    (r"setup|install|configure", "Setup and Configuration"),
    (r"build|compile|create", "Build and Creation"),
    (r"test|verify|check", "Testing and Verification"),
    (r"deploy|publish|release", "Deployment and Release"),
    (r"clean|teardown|remove", "Cleanup and Teardown"),
    (r"analyze|review|audit", "Analysis and Review"),
]


def infer_dependencies(tasks: list[Task]) -> list[Task]:
    """Infer task dependencies based on type and order."""
    _type_order: dict[str, int] = {
        "Setup and Configuration": 0,
        "Build and Creation": 1,
        "Testing and Verification": 2,
        "Deployment and Release": 3,
        "Analysis and Review": 2,  # Can run parallel with testing
    }

    task_types: dict[str, list[Task]] = {}
    for task in tasks:
        category = task.name.split(":")[0] if ":" in task.name else "General"
        if category not in task_types:
            task_types[category] = []
        task_types[category].append(task)

    # Simple sequential linking within categories
    for tasks_in_cat in task_types.values():
        for i in range(1, len(tasks_in_cat)):
            # Add dependency on previous task in same category
            prev_id = tasks_in_cat[i - 1].id
            if prev_id not in tasks_in_cat[i].dependencies:
                tasks_in_cat[i].dependencies.append(prev_id)

    return tasks


class TaskDecomposer:
    """Decomposes complex goals into executable task graphs.

    Uses LLM-based extraction when available (ollama by default),
    with pattern-matching fallback for simple or offline scenarios.
    """

    DEFAULT_MODEL = "qwen3.5-9b"

    def __init__(
        self,
        llm_provider: str = "ollama",
        llm_model: str | None = None,
        llm_base_url: str | None = None,
    ):
        self.llm_provider = llm_provider
        self.llm_model = llm_model or self.DEFAULT_MODEL
        self.llm_base_url = llm_base_url
        self._task_counter = 0
        self._llm_available: bool | None = None

    def decompose(self, goal: str, use_llm: bool = False) -> TaskGraph:
        """Decompose a natural language goal into a task graph.

        Args:
            goal: The natural language goal to decompose.
            use_llm: If True, attempt LLM-based decomposition first,
                     falling back to pattern matching on failure.
                     Default is False (pattern-matching only for reliability).
        """
        graph = TaskGraph(goal=goal)

        if use_llm:
            tasks = self._extract_tasks_llm(goal)
            if tasks:
                graph.tasks = tasks
                valid, err = self.validate_graph(graph)
                if valid:
                    return graph
                logger.warning("LLM decomposition produced invalid graph: %s", err)
                # Fall through to pattern matching

        # Pattern matching fallback
        tasks = self._extract_tasks_fallback(goal)
        graph.tasks = tasks
        return graph

    # -------------------------------------------------------------------------
    # LLM-based extraction
    # -------------------------------------------------------------------------

    _DECOMPOSE_PROMPT = """You are a task planning assistant. Given a goal, decompose it into atomic executable tasks.

Return a JSON array of task objects. Each task has:
- name: short descriptive name (max 60 chars)
- description: what this task does (max 200 chars)
- category: one of "Setup and Configuration", "Build and Creation", "Testing and Verification", "Deployment and Release", "Cleanup and Teardown", "Analysis and Review", "General"
- parallel_group: null or a string group name if this task can run concurrently with others in the same group
- success_criteria: how to know this task succeeded (max 100 chars)

Goal: {goal}

Return ONLY the JSON array, no markdown, no explanation.
Example: [{{"name": "Setup environment", "description": "Install dependencies", "category": "Setup and Configuration", "parallel_group": null, "success_criteria": "Dependencies installed"}}]
"""

    def _extract_tasks_llm(self, goal: str) -> list[Task]:
        """Extract tasks using LLM. Returns empty list on failure."""
        if self._llm_available is False:
            return []  # Don't retry if known unavailable

        try:
            import ollama
        except ImportError:
            logger.debug("ollama package not available, using fallback")
            self._llm_available = False
            return []

        try:
            base_url = self.llm_base_url or "http://localhost:11434"
            client = ollama.Client(host=base_url, timeout=10.0)
            response = client.chat(
                model=self.llm_model,
                messages=[{"role": "user", "content": self._DECOMPOSE_PROMPT.format(goal=goal)}],
                options={"temperature": 0.3, "num_predict": 512},
            )
            content = (response.message.content or "").strip()

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("\n", 1)[0]
            content = content.strip()

            parsed = json.loads(content)
            if not isinstance(parsed, list):
                logger.warning("LLM returned non-list: %s", type(parsed))
                return []

            tasks = [self._llm_entry_to_task(entry) for entry in parsed]
            # Infer dependencies between LLM-generated tasks
            tasks = infer_dependencies(tasks)
            return tasks

        except Exception as exc:  # pragma: no cover — network, model, parse errors
            logger.warning("LLM decomposition failed: %s", exc)
            self._llm_available = False
            return []

    def _llm_entry_to_task(self, entry: dict[str, Any]) -> Task:
        """Convert an LLM JSON entry to a Task."""
        self._task_counter += 1
        return Task(
            id=f"task_{self._task_counter}",
            name=str(entry.get("name", ""))[:60],
            description=str(entry.get("description", ""))[:200],
            category=entry.get("category", "General"),
            parallel_group=entry.get("parallel_group"),
            success_criteria=str(entry.get("success_criteria", "Task completed"))[:100],
        )

    # -------------------------------------------------------------------------
    # Pattern-matching fallback
    # -------------------------------------------------------------------------

    def _extract_tasks_fallback(self, goal: str) -> list[Task]:
        """Extract tasks from goal text using pattern matching."""
        tasks = []
        goal_lower = goal.lower()

        if "and" in goal_lower or "," in goal_lower:
            parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", goal)
            for i, part in enumerate(parts):
                part = part.strip().strip(".")
                if len(part) > 3:
                    task = self._create_task_fallback(part, i)
                    tasks.append(task)
        else:
            tasks.append(self._create_task_fallback(goal.strip(), 0))

        return infer_dependencies(tasks)

    def _create_task_fallback(self, description: str, index: int) -> Task:
        """Create a task from description using pattern classification."""
        self._task_counter += 1

        task_type = "General"
        for pattern, category in DECOMPOSE_PATTERNS:
            if re.search(pattern, description.lower()):
                task_type = category
                break

        task_name = f"{task_type}: {description[:50]}"
        success_criteria = self._infer_success_criteria(task_type)

        return Task(
            id=f"task_{self._task_counter}",
            name=task_name,
            description=description,
            success_criteria=success_criteria,
        )

    def _infer_success_criteria(self, task_type: str) -> str:
        """Infer success criteria from task type."""
        criteria_map: dict[str, str] = {
            "Setup and Configuration": "Configuration completed without errors",
            "Build and Creation": "Build artifacts created successfully",
            "Testing and Verification": "All tests pass",
            "Deployment and Release": "Deployment successful and accessible",
            "Analysis and Review": "Analysis complete with findings",
            "General": "Task completed as specified",
        }
        return criteria_map.get(task_type, criteria_map["General"])

    def plan_execution(self, graph: TaskGraph) -> list[list[Task]]:
        """Plan execution order respecting dependencies."""
        execution_plan: list[list[Task]] = []
        completed: set[str] = set()
        max_iterations = len(graph.tasks) + 1  # Prevent infinite loop
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            ready = graph.get_ready_tasks(completed)
            if not ready:
                break

            for task in ready:
                execution_plan.append([task])
                completed.add(task.id)

        return execution_plan

    def execute(self, graph: TaskGraph) -> TaskGraph:
        """Execute task graph with dependency respect."""
        plan = self.plan_execution(graph)

        for batch in plan:
            for task in batch:
                task.mark_running()

        # In a real implementation, this would run tasks
        # For now, just mark as done
        for task in graph.tasks:
            if task.status == TaskStatus.RUNNING:
                task.mark_done()

        return graph

    def validate_graph(self, graph: TaskGraph) -> tuple[bool, str | None]:
        """Validate task graph for cycles and missing dependencies."""
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()

        def has_cycle(task_id: str) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            task = graph.get_task(task_id)
            if task:
                for dep_id in task.dependencies:
                    if dep_id not in visited:
                        if has_cycle(dep_id):
                            return True
                    elif dep_id in rec_stack:
                        return True

            rec_stack.remove(task_id)
            return False

        for task in graph.tasks:
            if task.id not in visited:
                if has_cycle(task.id):
                    return False, f"Cycle detected involving task {task.id}"

        # Check for missing dependencies
        task_ids = {t.id for t in graph.tasks}
        for task in graph.tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    return False, f"Task {task.id} depends on non-existent task {dep_id}"

        return True, None
