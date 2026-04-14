"""Tests for memory module."""

import tempfile

import pytest

from riks_context_engine.memory import (
    EpisodicMemory,
    MemoryEntry,
    MemoryType,
    OllamaEmbedder,
    OllamaEmbeddingError,
    ProceduralMemory,
    SemanticMemory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_temp_path() -> str:
    return tempfile.mktemp(suffix=".json")


def new_temp_db() -> str:
    return tempfile.mktemp(suffix=".db")


# ---------------------------------------------------------------------------
# MemoryEntry / MemoryType (base)
# ---------------------------------------------------------------------------


class TestMemoryType:
    def test_memory_type_values(self):
        assert MemoryType.EPISODIC.value == "episodic"
        assert MemoryType.SEMANTIC.value == "semantic"
        assert MemoryType.PROCEDURAL.value == "procedural"


class TestMemoryEntry:
    def test_record_access_increments_count(self):
        entry = MemoryEntry(
            id="test_1",
            type=MemoryType.EPISODIC,
            content="hello",
        )
        assert entry.access_count == 0
        entry.record_access()
        assert entry.access_count == 1
        assert entry.last_accessed is not None

    def test_to_dict_roundtrip(self):
        entry = MemoryEntry(
            id="test_2",
            type=MemoryType.SEMANTIC,
            content="Paris is the capital of France",
            importance=0.95,
            embedding=[0.1, 0.2, 0.3],
            metadata={"source": "wikipedia"},
        )
        data = entry.to_dict()
        restored = MemoryEntry.from_dict(data)
        assert restored.id == entry.id
        assert restored.type == entry.type
        assert restored.content == entry.content
        assert restored.importance == entry.importance
        assert restored.embedding == entry.embedding


# ---------------------------------------------------------------------------
# EpisodicMemory
# ---------------------------------------------------------------------------


class TestEpisodicMemory:
    def test_add_entry(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        entry = mem.add(content="Test observation", importance=0.8, tags=["test"])
        assert entry.content == "Test observation"
        assert entry.importance == 0.8
        assert "test" in entry.tags

    def test_episodic_entry_has_id(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        entry = mem.add("something happened")
        assert entry.id.startswith("ep_")

    def test_add_persists_to_disk(self):
        path = new_temp_path()
        mem = EpisodicMemory(storage_path=path)
        mem.add("first fact", importance=0.9, tags=["fact"])
        mem.add("second fact", importance=0.7, tags=["fact"])

        # Re-open – data should survive
        mem2 = EpisodicMemory(storage_path=path)
        results = mem2.query(tags=["fact"])
        assert len(results) == 2
        contents = {r.content for r in results}
        assert "first fact" in contents
        assert "second fact" in contents

    def test_query_by_tag(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        mem.add("alpha", tags=["a", "common"])
        mem.add("beta", tags=["b", "common"])
        mem.add("gamma", tags=["a"])

        results = mem.query(tags=["a"])
        assert len(results) == 2
        contents = {r.content for r in results}
        assert "alpha" in contents
        assert "gamma" in contents
        assert "beta" not in contents

    def test_query_by_text(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        mem.add("The sky is blue today")
        mem.add("Roses are red")
        results = mem.query(query="blue")
        assert len(results) == 1
        assert results[0].content == "The sky is blue today"

    def test_prune_removes_low_importance(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        for i in range(10):
            mem.add(f"fact {i}", importance=i / 10.0)
        assert len(mem._entries) == 10
        removed = mem.prune(max_entries=5)
        assert removed == 5
        assert len(mem._entries) == 5
        # Remaining should be the highest importance ones
        remaining = list(mem._entries.values())
        assert all(e.importance >= 0.5 for e in remaining)

    def test_delete_entry(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        entry = mem.add("to delete")
        assert mem.delete(entry.id) is True
        assert mem.delete(entry.id) is False  # already gone

    def test_get_records_access(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        entry = mem.add("remember this")
        first_access = entry.access_count
        retrieved = mem.get(entry.id)
        assert retrieved is not None
        assert retrieved.access_count == first_access + 1

    def test_stats(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        mem.add("alpha", importance=0.5, tags=["tag_a"])
        mem.add("beta", importance=0.6, tags=["tag_a"])
        mem.add("gamma", importance=0.7, tags=["tag_b"])
        stats = mem.stats()
        assert stats["total"] == 3
        assert stats["avg_importance"] == pytest.approx(0.6)
        assert stats["by_tag"]["tag_a"] == 2

    def test_clear(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        mem.add("one")
        mem.add("two")
        mem.clear()
        assert len(mem._entries) == 0

    def test_to_memory_entry_roundtrip(self):
        mem = EpisodicMemory(storage_path=new_temp_path())
        entry = mem.add("hello world", importance=0.8, tags=["greeting"])
        me = entry.to_memory_entry()
        assert me.type == MemoryType.EPISODIC
        assert me.content == "hello world"
        assert me.metadata["tags"] == ["greeting"]


# ---------------------------------------------------------------------------
# SemanticMemory
# ---------------------------------------------------------------------------


class TestSemanticMemory:
    def test_add_entry(self):
        mem = SemanticMemory(db_path=new_temp_db())
        entry = mem.add(
            subject="Rik",
            predicate="is",
            object="an AI assistant",
            confidence=0.95,
            generate_embedding=False,
        )
        assert entry.subject == "Rik"
        assert entry.predicate == "is"
        assert entry.confidence == 0.95

    def test_access_count_increments(self):
        mem = SemanticMemory(db_path=new_temp_db())
        entry = mem.add("Vahit", "works at", "opsiton", generate_embedding=False)
        assert entry.access_count == 0
        _ = mem.get(entry.id)
        retrieved = mem.get(entry.id)
        assert retrieved is not None
        assert retrieved.access_count == 2

    def test_query_by_subject(self):
        mem = SemanticMemory(db_path=new_temp_db())
        mem.add("Paris", "capital of", "France", generate_embedding=False)
        mem.add("London", "capital of", "UK", generate_embedding=False)
        results = mem.query(subject="Paris")
        assert len(results) == 1
        assert results[0].object == "France"

    def test_query_by_predicate(self):
        mem = SemanticMemory(db_path=new_temp_db())
        mem.add("Alice", "knows", "Bob", generate_embedding=False)
        mem.add("Bob", "knows", "Carol", generate_embedding=False)
        results = mem.query(predicate="knows")
        assert len(results) == 2

    def test_delete_entry(self):
        mem = SemanticMemory(db_path=new_temp_db())
        entry = mem.add("Test", "delete me", "row", generate_embedding=False)
        assert mem.delete(entry.id) is True
        assert mem.get(entry.id) is None

    def test_stats(self):
        mem = SemanticMemory(db_path=new_temp_db())
        mem.add("A", "B", "C", confidence=0.8, generate_embedding=False)
        mem.add("D", "E", "F", confidence=0.9, generate_embedding=False)
        stats = mem.stats()
        assert stats["total"] == 2
        assert stats["avg_confidence"] == pytest.approx(0.85)
        assert stats["with_embedding"] == 0  # no embeddings generated

    def test_clear(self):
        mem = SemanticMemory(db_path=new_temp_db())
        mem.add("X", "Y", "Z", generate_embedding=False)
        mem.clear()
        assert mem.stats()["total"] == 0

    def test_recall_requires_embedder(self):
        """recall() should return [] gracefully if embedder is unavailable."""
        mem = SemanticMemory(db_path=new_temp_db())
        mem.add("alpha", "beta", "gamma", generate_embedding=False)
        # No embedder set – recall should return empty without crashing
        results = mem.recall("anything")
        assert results == []

    def test_to_memory_entry_roundtrip(self):
        mem = SemanticMemory(db_path=new_temp_db())
        entry = mem.add("Vahit", "lives in", "Istanbul", generate_embedding=False)
        me = entry.to_memory_entry()
        assert me.type == MemoryType.SEMANTIC
        assert "Vahit" in me.content


# ---------------------------------------------------------------------------
# ProceduralMemory
# ---------------------------------------------------------------------------


class TestProceduralMemory:
    def test_store_procedure(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        proc = mem.store(
            name="Deploy Service",
            description="Deploy a microservice to Kubernetes",
            steps=["build image", "push to registry", "apply k8s manifests"],
        )
        assert proc.name == "Deploy Service"
        assert len(proc.steps) == 3
        assert proc.use_count == 0

    def test_procedure_has_id(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        proc = mem.store("Test Proc", "A test", ["step1"])
        assert proc.id.startswith("pr_")

    def test_store_persists_to_disk(self):
        path = new_temp_path()
        mem = ProceduralMemory(storage_path=path)
        mem.store("Build Image", "Build docker image", ["docker build"])
        mem2 = ProceduralMemory(storage_path=path)
        results = mem2.find(query="docker")
        assert len(results) == 1
        assert results[0].name == "Build Image"

    def test_recall_by_name(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        mem.store("Send Email", "Send an email", ["compose", "send"])
        result = mem.recall("Send Email")
        assert result is not None
        assert result.name == "Send Email"

    def test_recall_case_insensitive(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        mem.store("Deploy Service", "Deploy a service", ["step1"])
        assert mem.recall("deploy service") is not None

    def test_find_by_tag(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        mem.store("Alpha", "A proc", ["s1"], tags=["dev", "infra"])
        mem.store("Beta", "B proc", ["s2"], tags=["dev"])
        mem.store("Gamma", "C proc", ["s3"], tags=["infra"])
        results = mem.find(tags=["infra"])
        assert len(results) == 2
        names = {r.name for r in results}
        assert "Alpha" in names
        assert "Gamma" in names

    def test_find_by_query(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        mem.store("Send Email", "Send email via SMTP", ["connect", "send"])
        mem.store("Send SMS", "Send SMS via API", ["prepare", "send"])
        results = mem.find(query="email")
        assert len(results) == 1
        assert results[0].name == "Send Email"

    def test_record_execution_updates_stats(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        proc = mem.store("Test", "Test procedure", ["step1"])
        assert proc.success_rate == 1.0
        assert proc.use_count == 0
        mem.record_execution(proc.id, success=True)
        updated = mem.get(proc.id)
        assert updated is not None
        assert updated.use_count == 1
        assert updated.success_rate == 1.0
        mem.record_execution(proc.id, success=False)
        updated2 = mem.get(proc.id)
        assert updated2 is not None
        assert updated2.use_count == 2
        assert updated2.success_rate == pytest.approx(0.5)

    def test_delete_procedure(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        proc = mem.store("Temp", "Temporary", ["s1"])
        assert mem.delete(proc.id) is True
        assert mem.delete(proc.id) is False
        assert mem.recall("Temp") is None

    def test_stats(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        mem.store("Alpha", "A", ["s1"], tags=["x"])
        mem.store("Beta", "B", ["s2"], tags=["x", "y"])
        mem.store("Gamma", "G", ["s3"], tags=["y"])
        stats = mem.stats()
        assert stats["total"] == 3
        assert stats["avg_success_rate"] == 1.0  # all new = 1.0
        assert stats["by_tag"]["x"] == 2
        assert stats["by_tag"]["y"] == 2

    def test_to_memory_entry_roundtrip(self):
        mem = ProceduralMemory(storage_path=new_temp_path())
        proc = mem.store("Deploy", "Deploy to k8s", ["build", "push", "apply"], tags=["k8s"])
        me = proc.to_memory_entry()
        assert me.type == MemoryType.PROCEDURAL
        assert me.metadata["name"] == "Deploy"
        assert me.metadata["steps"] == ["build", "push", "apply"]
        assert me.metadata["tags"] == ["k8s"]


# ---------------------------------------------------------------------------
# OllamaEmbedder (unit with mocked httpx)
# ---------------------------------------------------------------------------


class TestOllamaEmbedder:
    def test_embed_bad_host_raises(self):
        embedder = OllamaEmbedder(base_url="http://localhost:19999")
        with pytest.raises(OllamaEmbeddingError, match="Cannot connect"):
            embedder.embed("hello world")

    def test_is_available_returns_false_on_error(self):
        embedder = OllamaEmbedder(base_url="http://localhost:19999")
        assert embedder.is_available() is False

    def test_close_is_idempotent(self):
        embedder = OllamaEmbedder()
        embedder.close()
        embedder.close()  # should not raise


# ---------------------------------------------------------------------------
# Cross-tier integration (basic)
# ---------------------------------------------------------------------------


class TestCrossTier:
    def test_all_memory_entries_have_required_fields(self):
        """Verify every tier's entry type can produce a MemoryEntry."""
        ep_mem = EpisodicMemory(storage_path=new_temp_path())
        ep_entry = ep_mem.add("saw a cat", importance=0.7, tags=["animal"])
        assert ep_entry.to_memory_entry().type == MemoryType.EPISODIC

        sm_mem = SemanticMemory(db_path=new_temp_db())
        sm_entry = sm_mem.add("cat", "is a", "mammal", generate_embedding=False)
        assert sm_entry.to_memory_entry().type == MemoryType.SEMANTIC

        pr_mem = ProceduralMemory(storage_path=new_temp_path())
        pr_proc = pr_mem.store("Pet Cat", "How to pet a cat", ["approach", "stroke"])
        assert pr_proc.to_memory_entry().type == MemoryType.PROCEDURAL

    def test_episodic_and_procedural_share_json_backend(self, tmp_path):
        """Both episodic and procedural use JSON and survive restart."""
        ep_path = str(tmp_path / "ep.json")
        pr_path = str(tmp_path / "pr.json")

        ep1 = EpisodicMemory(storage_path=ep_path)
        ep1.add("session fact")
        ep1.add("another fact")

        pr1 = ProceduralMemory(storage_path=pr_path)
        pr1.store("Test Skill", "Test desc", ["do thing"])

        # Re-open from disk
        ep2 = EpisodicMemory(storage_path=ep_path)
        pr2 = ProceduralMemory(storage_path=pr_path)

        assert len(ep2.query()) == 2
        assert pr2.find()[0].name == "Test Skill"
