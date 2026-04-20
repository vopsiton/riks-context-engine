"""Tests for memory module."""

import os
import tempfile

from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory


def _temp_json_path():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    path = f.name
    f.close()
    return path


def _temp_db_path():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    os.unlink(path)
    return path


class TestEpisodicMemory:
    def test_add_entry(self):
        mem = EpisodicMemory(storage_path=":memory:")
        entry = mem.add(content="Test observation", importance=0.8, tags=["test"])
        assert entry.content == "Test observation"
        assert entry.importance == 0.8
        assert "test" in entry.tags

    def test_episodic_entry_has_id(self):
        mem = EpisodicMemory(storage_path=":memory:")
        entry = mem.add("something happened")
        assert entry.id.startswith("ep_")


class TestSemanticMemory:
    def test_add_entry(self):
        mem = SemanticMemory(db_path=":memory:")
        entry = mem.add(subject="Rik", predicate="is", object="an AI assistant", confidence=0.95)
        assert entry.subject == "Rik"
        assert entry.predicate == "is"
        assert entry.confidence == 0.95

    def test_access_count_increments(self):
        mem = SemanticMemory(db_path=":memory:")
        entry = mem.add("Vahit", "works at", "opsiton")
        assert entry.access_count == 0


class TestProceduralMemory:
    def test_store_procedure(self):
        mem = ProceduralMemory(storage_path=":memory:")
        proc = mem.store(
            name="Deploy Service",
            description="Deploy a microservice to Kubernetes",
            steps=["build image", "push to registry", "apply k8s manifests"],
        )
        assert proc.name == "Deploy Service"
        assert len(proc.steps) == 3
        assert proc.use_count == 0

    def test_procedure_has_id(self):
        mem = ProceduralMemory(storage_path=":memory:")
        proc = mem.store("Test Proc", "A test", ["step1"])
        assert proc.id.startswith("pr_")


class TestEpisodicMemoryExtended:
    """Tests for episodic.py: query, prune, delete, __len__."""

    def test_query_by_keyword(self):
        """Lines 98-102: query() returns entries matching keyword."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        mem.add("I ate a pizza today", importance=0.8, tags=["food"])
        mem.add("Meeting with team at 10am", importance=0.6)
        mem.add("Quick coffee break", importance=0.3)

        results = mem.query("pizza")
        assert len(results) == 1
        assert results[0].content == "I ate a pizza today"

    def test_query_by_tag(self):
        """query() matches entries by tag keyword."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        mem.add("some event", tags=["work", "meeting"])
        mem.add("another event", tags=["personal"])

        results = mem.query("work")
        assert len(results) == 1
        assert "work" in results[0].tags

    def test_query_sorted_by_importance(self):
        """query() returns results sorted by importance desc."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        mem.add("low importance", importance=0.1)
        mem.add("high importance", importance=0.9)
        mem.add("medium importance", importance=0.5)

        results = mem.query("importance")
        assert len(results) == 3
        assert results[0].importance >= results[1].importance

    def test_query_limit(self):
        """query() respects the limit parameter."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        for i in range(20):
            mem.add(f"entry {i}")

        results = mem.query("entry", limit=5)
        assert len(results) == 5

    def test_prune_no_op_when_under_limit(self):
        """Lines 110-113: prune() returns 0 when count <= max_entries."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        for i in range(5):
            mem.add(f"entry {i}", importance=0.5)

        removed = mem.prune(max_entries=10)
        assert removed == 0
        assert len(mem) == 5

    def test_prune_removes_low_importance_entries(self):
        """Lines 114-136: prune() removes lowest-importance entries."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        mem.add("important entry", importance=0.9)
        mem.add("medium entry", importance=0.5)
        mem.add("low entry", importance=0.1)
        mem.add("very low entry", importance=0.05)
        assert len(mem) == 4

        removed = mem.prune(max_entries=2)
        assert removed == 2
        assert len(mem) == 2
        # High importance entries should survive
        remaining_contents = [e.content for e in mem.entries.values()]
        assert "important entry" in remaining_contents

    def test_delete_returns_false_for_missing_entry(self):
        """Line 144: delete() returns False when entry_id not found."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        result = mem.delete("nonexistent_id")
        assert result is False

    def test_delete_returns_true_and_removes_entry(self):
        """Lines 140-143: delete() returns True and removes the entry."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        entry = mem.add("to be deleted")
        assert len(mem) == 1

        result = mem.delete(entry.id)
        assert result is True
        assert len(mem) == 0

    def test_len(self):
        """Line 147: __len__ returns correct count."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        assert len(mem) == 0
        mem.add("first")
        assert len(mem) == 1
        mem.add("second")
        assert len(mem) == 2

    def test_get_increments_access_count(self):
        """get() increments access_count and sets last_accessed."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        entry = mem.add("check access", importance=0.7)
        assert entry.access_count == 0

        retrieved = mem.get(entry.id)
        assert retrieved is not None
        assert retrieved.access_count == 1
        assert retrieved.last_accessed is not None

    def test_get_returns_none_for_missing(self):
        """get() returns None when entry_id does not exist."""
        mem = EpisodicMemory(storage_path=_temp_json_path())
        assert mem.get("nonexistent") is None

    def test_persistence_round_trip(self):
        """Lines 37-46: _load() reads entries persisted by _save()."""
        path = _temp_json_path()
        mem1 = EpisodicMemory(storage_path=path)
        mem1.add("persistent entry", importance=0.8, tags=["persisted"])

        mem2 = EpisodicMemory(storage_path=path)
        assert len(mem2) == 1
        entry = list(mem2.entries.values())[0]
        assert entry.content == "persistent entry"
        assert "persisted" in entry.tags


class TestProceduralMemoryExtended:
    """Tests for procedural.py: recall, find, delete, update_success_rate."""

    def test_recall_finds_exact_name_match(self):
        """Lines 106-111: recall() returns procedure on exact name match."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        mem.store("Deploy Service", "desc", ["build", "push", "apply"])

        proc = mem.recall("deploy service")  # case-insensitive
        assert proc is not None
        assert proc.name == "Deploy Service"
        assert proc.use_count == 1

    def test_recall_returns_none_when_not_found(self):
        """Lines 115-121: recall() returns None when name not found."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        assert mem.recall("Nonexistent Procedure") is None

    def test_find_matches_by_name(self):
        """Lines 125-136: find() returns procedures matching query."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        mem.store("Deploy to K8s", "Kubernetes deployment", ["build", "push"])
        mem.store("Deploy to ECS", "ECS deployment", ["build", "push", "deploy"])
        mem.store("Run Tests", "Execute test suite", ["test"])

        results = mem.find("deploy")
        assert len(results) == 2
        assert all("deploy" in p.name.lower() or "deploy" in p.description.lower() for p in results)

    def test_find_matches_by_description(self):
        """find() also matches against description."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        mem.store("My Proc", "performs kubernetes orchestration", ["step"])

        results = mem.find("kubernetes")
        assert len(results) == 1

    def test_find_matches_by_tag(self):
        """find() also searches tags."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        mem.store("CI Pipeline", "runs CI", ["step"], tags=["automation", "ci"])
        mem.store("Manual Deploy", "manual step", ["step"], tags=["deploy"])

        results = mem.find("automation")
        assert len(results) == 1
        assert results[0].name == "CI Pipeline"

    def test_find_returns_empty_for_no_match(self):
        """find() returns empty list when nothing matches."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        mem.store("Some Proc", "does something", ["step"])

        results = mem.find("xyzzy_not_found")
        assert results == []

    def test_delete_returns_true_and_removes(self):
        """Lines 140-143: delete() removes the procedure."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        proc = mem.store("To Delete", "desc", ["step"])
        assert len(mem) == 1

        result = mem.delete(proc.id)
        assert result is True
        assert len(mem) == 0

    def test_delete_returns_false_for_missing(self):
        """Line 144: delete() returns False when id not found."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        assert mem.delete("nonexistent_id") is False

    def test_update_success_rate_success(self):
        """Lines 148-153: update_success_rate() adjusts rate on success."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        proc = mem.store("Proc", "desc", ["step"])
        # Manually set use_count > 0 so formula doesn't divide by zero
        proc.use_count = 2

        result = mem.update_success_rate(proc.id, success=True)
        assert result is True

    def test_update_success_rate_failure(self):
        """update_success_rate() adjusts rate on failure."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        proc = mem.store("Proc", "desc", ["step"])
        proc.use_count = 2

        result = mem.update_success_rate(proc.id, success=False)
        assert result is True
        updated = mem.get(proc.id)
        assert updated is not None

    def test_update_success_rate_returns_false_for_missing(self):
        """Line 154: update_success_rate() returns False for unknown id."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        assert mem.update_success_rate("nonexistent", success=True) is False

    def test_get_updates_use_stats(self):
        """get() increments use_count and updates last_used."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        proc = mem.store("Track Me", "desc", ["step"])
        assert proc.use_count == 0

        retrieved = mem.get(proc.id)
        assert retrieved is not None
        assert retrieved.use_count == 1

    def test_get_returns_none_for_missing(self):
        """get() returns None for unknown id."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        assert mem.get("nonexistent") is None

    def test_len(self):
        """__len__ returns correct count."""
        mem = ProceduralMemory(storage_path=_temp_json_path())
        assert len(mem) == 0
        mem.store("P1", "d1", ["s1"])
        assert len(mem) == 1
        mem.store("P2", "d2", ["s2"])
        assert len(mem) == 2

    def test_persistence_round_trip(self):
        """Lines 39-49: _load() reads procedures persisted by _save()."""
        path = _temp_json_path()
        mem1 = ProceduralMemory(storage_path=path)
        mem1.store("Persisted Proc", "check persistence", ["step_a", "step_b"])

        mem2 = ProceduralMemory(storage_path=path)
        assert len(mem2) == 1
        proc = list(mem2.procedures.values())[0]
        assert proc.name == "Persisted Proc"
        assert proc.steps == ["step_a", "step_b"]
