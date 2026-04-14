"""Tests for memory module."""



from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory


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
