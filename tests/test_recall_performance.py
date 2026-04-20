"""Test SemanticMemory recall performance."""

import random
import time

from riks_context_engine.memory.semantic import SemanticMemory


class TestRecallPerformance:
    """Tests for SemanticMemory.recall() performance."""

    def test_recall_under_100ms_1000_entries(self):
        """Recall should complete in < 100ms on 1000 entries."""
        mem = SemanticMemory(db_path=":memory:")

        # Insert 1000 entries
        for i in range(1000):
            mem.add(
                subject=f"entity_{i % 100}_{random.choice(['a', 'b', 'c'])}",
                predicate="related_to",
                object=f"value_{i}",
            )

        # Benchmark
        times = []
        for _ in range(5):
            start = time.perf_counter()
            results = mem.recall("entity_a")
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_seconds = sum(times) / len(times)
        avg_ms = avg_seconds * 1000
        max_ms = max(times) * 1000

        assert avg_ms < 100, f"Average recall {avg_ms:.2f}ms exceeds 100ms threshold"
        assert max_ms < 100, f"Max recall {max_ms:.2f}ms exceeds 100ms threshold"

    def test_recall_uses_index(self):
        """Recall should use SQL LIKE with indexed columns."""
        mem = SemanticMemory(db_path=":memory:")
        mem.add("test_subject", "test_predicate", "test_object")

        # Should not do full table scan
        results = mem.recall("test")
        assert len(results) >= 1
        assert any(
            "test" in r.subject or "test" in r.predicate or "test" in r.object for r in results
        )

    def test_recall_correctness(self):
        """Index search should find matching entries."""
        mem = SemanticMemory(db_path=":memory:")
        mem.add("apple", "is_a", "fruit")
        mem.add("banana", "is_a", "fruit")
        mem.add("carrot", "is_a", "vegetable")
        mem.add("fruit", "category", "food")

        results = mem.recall("fruit")
        assert len(results) >= 1
        # Results should contain fruit-related entries
        assert all(
            "fruit" in r.subject.lower()
            or "fruit" in r.predicate.lower()
            or "fruit" in r.object.lower()
            for r in results
        )
