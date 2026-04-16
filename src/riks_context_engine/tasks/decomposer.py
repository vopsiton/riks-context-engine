"""Task decomposition - goal → executable steps."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


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
    parallel_group: Optional[str] = None  # Tasks in same group can run in parallel
    success_criteria: Optional[str] = None
    rollback_steps: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    retry_count: int = 0

    def mark_done(self):
        self.status = TaskStatus.DONE
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self):
        self.status = TaskStatus.FAILED

    def mark_running(self):
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

    def get_task(self, task_id: str) -> Optional[Task]:
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
    type_order = {
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

    Uses pattern-based extraction from natural language to build
    a dependency graph of tasks with success criteria and
    rollback possibilities.
    """

    def __init__(self, llm_provider: str = "ollama"):
        self.llm_provider = llm_provider
        self._task_counter = 0

    def decompose(self, goal: str) -> TaskGraph:
        """Decompose a natural language goal into a task graph."""
        graph = TaskGraph(goal=goal)
        tasks = self._extract_tasks(goal)
        graph.tasks = tasks
        return graph

    def _extract_tasks(self, goal: str) -> list[Task]:
        """Extract tasks from goal text using pattern matching."""
        tasks = []
        goal_lower = goal.lower()

        # Check for common goal patterns
        if "and" in goal_lower or "," in goal_lower:
            # Split by common delimiters
            parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", goal)
            for i, part in enumerate(parts):
                part = part.strip().strip(".")
                if len(part) > 3:
                    task = self._create_task(part, i)
                    tasks.append(task)
        else:
            # Single task
            tasks.append(self._create_task(goal.strip(), 0))

        # Infer dependencies
        tasks = infer_dependencies(tasks)

        return tasks

    def _create_task(self, description: str, index: int) -> Task:
        """Create a task from description."""
        self._task_counter += 1

        # Classify task type
        task_type = "General"
        for pattern, category in DECOMPOSE_PATTERNS:
            if re.search(pattern, description.lower()):
                task_type = category
                break

        # Build task name
        task_name = f"{task_type}: {description[:50]}"

        # Determine success criteria based on type
        success_criteria = self._infer_success_criteria(task_type, description)

        return Task(
            id=f"task_{self._task_counter}",
            name=task_name,
            description=description,
            success_criteria=success_criteria,
        )

    def _infer_success_criteria(self, task_type: str, description: str) -> str:
        """Infer success criteria from task type and description."""
        criteria_map = {
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
            # batch is list[Task] (sequential) or list[list[Task]] (parallel batches)
            if batch and isinstance(batch[0], list):
                # Parallel: batch is list of task lists [[task1, task2], ...]
                for task_list in batch:
                    for task in task_list:
                        task.mark_running()
            else:
                # Sequential: batch is list of Tasks [task1, task2, ...]
                for task in batch:
                    task.mark_running()

        # In a real implementation, this would run tasks
        # For now, just mark as done
        for task in graph.tasks:
            if task.status == TaskStatus.RUNNING:
                task.mark_done()

        return graph

    def validate_graph(self, graph: TaskGraph) -> tuple[bool, Optional[str]]:
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
