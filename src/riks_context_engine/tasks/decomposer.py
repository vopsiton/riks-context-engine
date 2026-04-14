"""Task decomposition - goal → executable steps."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


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
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    retry_count: int = 0


@dataclass
class TaskGraph:
    """A graph of decomposed tasks."""

    goal: str
    tasks: list[Task] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


class TaskDecomposer:
    """Decomposes complex goals into executable task graphs.

    Uses LLM-based extraction from natural language to build
    a dependency graph of tasks with success criteria and
    rollback possibilities.
    """

    def __init__(self, llm_provider: str = "ollama"):
        self.llm_provider = llm_provider

    def decompose(self, goal: str) -> TaskGraph:
        """Decompose a natural language goal into a task graph."""
        graph = TaskGraph(goal=goal)
        return graph

    def plan_execution(self, graph: TaskGraph) -> list[list[Task]]:
        """Plan execution order respecting dependencies."""
        return []

    def execute(self, graph: TaskGraph) -> TaskGraph:
        """Execute task graph with dependency respect."""
        return graph
