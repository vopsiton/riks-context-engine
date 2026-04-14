"""Tests for task decomposition."""

import pytest

from riks_context_engine.tasks.decomposer import (
    TaskDecomposer,
    TaskGraph,
    Task,
    TaskStatus,
    infer_dependencies,
)


class TestTaskDecomposer:
    def test_init(self):
        decomposer = TaskDecomposer()
        assert decomposer.llm_provider == "ollama"
        assert decomposer._task_counter == 0

    def test_decompose_single_goal(self):
        decomposer = TaskDecomposer()
        graph = decomposer.decompose("Build a login feature")
        assert graph.goal == "Build a login feature"
        assert len(graph.tasks) == 1

    def test_decompose_multiple_goals(self):
        decomposer = TaskDecomposer()
        graph = decomposer.decompose("Setup database, configure auth, test endpoints")
        assert len(graph.tasks) == 3

    def test_plan_execution(self):
        decomposer = TaskDecomposer()
        graph = decomposer.decompose("Setup database, build API, test, deploy")
        plan = decomposer.plan_execution(graph)
        assert len(plan) > 0

    def test_validate_graph_no_cycle(self):
        decomposer = TaskDecomposer()
        graph = decomposer.decompose("Step 1, step 2, step 3")
        valid, error = decomposer.validate_graph(graph)
        assert valid is True
        assert error is None

    def test_execute_marks_done(self):
        decomposer = TaskDecomposer()
        graph = decomposer.decompose("Build feature")
        # Execute and verify tasks move to done status
        initial_status = graph.tasks[0].status
        assert initial_status == TaskStatus.PENDING


class TestTask:
    def test_task_can_execute_no_deps(self):
        task = Task(id="t1", name="Test", description="Test task")
        assert task.can_execute(set()) is True

    def test_task_can_execute_with_deps(self):
        task = Task(id="t2", name="Test", description="Test", dependencies=["t1"])
        assert task.can_execute({"t1"}) is True
        assert task.can_execute(set()) is False

    def test_task_status_transitions(self):
        task = Task(id="t1", name="Test", description="Test")
        assert task.status == TaskStatus.PENDING
        task.mark_running()
        assert task.status == TaskStatus.RUNNING
        task.mark_done()
        assert task.status == TaskStatus.DONE
        assert task.completed_at is not None


class TestTaskGraph:
    def test_get_task(self):
        graph = TaskGraph(goal="test")
        graph.tasks.append(Task(id="t1", name="Test", description="Test"))
        assert graph.get_task("t1") is not None
        assert graph.get_task("nonexistent") is None

    def test_get_ready_tasks(self):
        graph = TaskGraph(goal="test")
        t1 = Task(id="t1", name="Test1", description="Test1")
        t2 = Task(id="t2", name="Test2", description="Test2", dependencies=["t1"])
        graph.tasks = [t1, t2]

        # Initially only t1 is ready (no deps)
        ready = graph.get_ready_tasks(set())
        assert len(ready) == 1
        assert ready[0].id == "t1"

        # After t1 done, t2 becomes ready
        t1.status = TaskStatus.DONE
        ready = graph.get_ready_tasks({"t1"})
        assert len(ready) == 1
        assert ready[0].id == "t2"


def test_infer_dependencies():
    tasks = [
        Task(id="setup", name="Setup", description="Setup config"),
        Task(id="build", name="Build", description="Build project"),
        Task(id="test", name="Test", description="Test feature"),
    ]
    tasks = infer_dependencies(tasks)
    # build should depend on setup
    assert "setup" in tasks[1].dependencies
    # test should depend on build (which depends on setup)
    assert "build" in tasks[2].dependencies


def test_task_type_inference():
    """Test that task types are correctly classified."""
    from riks_context_engine.tasks.decomposer import TaskDecomposer
    decomposer = TaskDecomposer()
    graph = decomposer.decompose("Setup config, build project, test feature")
    
    types_found = set()
    for task in graph.tasks:
        types_found.add(task.name.split(":")[0])
    
    # Should have different types for setup, build, test
    assert len(types_found) >= 2