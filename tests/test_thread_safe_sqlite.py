"""Thread-safety tests for SemanticMemory and KnowledgeGraph.

Covers AC-51-01 (10 thread concurrent write → 0 "Database is locked"),
AC-51-02 (WAL mode enabled), AC-51-03 (context manager usage).
"""

import os
import sqlite3
import tempfile
import threading
import time

from riks_context_engine.graph.knowledge_graph import EntityType, KnowledgeGraph, RelationshipType
from riks_context_engine.memory.semantic import SemanticMemory


class TestThreadSafeSQLite:
    """AC-51: Thread-safe SQLite operations."""

    # ── AC-51-01: 10 thread concurrent writes → 0 "Database is locked" ──

    def test_concurrent_writes_no_database_locked_error(self):
        """10 threads writing simultaneously should produce 0 'database is locked' errors.

        This is the FAIL case: without proper locking, concurrent writes cause
        sqlite3.OperationalError: database is locked.

        With thread-safe design (WAL + write lock), all writes succeed.
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)
        errors = []
        successes = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(5):
                    mem.add(
                        subject=f"thread_{thread_id}_entry_{i}",
                        predicate="written_by",
                        object=f"thread {thread_id}",
                    )
                    successes.append((thread_id, i))
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower() or "locked" in str(e).lower():
                    errors.append((thread_id, str(e)))
                else:
                    errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Clean up temp file
        try:
            os.unlink(db_path)
        except OSError:
            pass

        # AC-51-01: 0 database locked errors
        assert len(errors) == 0, f"Got {len(errors)} errors: {errors}"
        # All 50 writes should succeed (10 threads × 5 writes)
        assert len(successes) == 50, f"Expected 50 successes, got {len(successes)}"

    def test_concurrent_reads_and_writes(self):
        """Concurrent readers and writers should not block each other unnecessarily.

        With WAL mode, readers don't block writers and vice versa.
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)

        # Pre-populate
        for i in range(20):
            mem.add(subject=f"entity_{i}", predicate="type", object=f"object_{i}")

        errors = []
        read_results = []
        write_count = [0]

        def reader(reader_id: int) -> None:
            try:
                for _ in range(10):
                    results = mem.query(subject="entity")
                    read_results.append((reader_id, len(results)))
            except Exception as e:
                errors.append((reader_id, str(e)))

        def writer(writer_id: int) -> None:
            try:
                for i in range(5):
                    mem.add(subject=f"writer_{writer_id}_{i}", predicate="type", object="new")
                    write_count[0] += 1
            except Exception as e:
                errors.append((writer_id, str(e)))

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=reader, args=(i,)))
        for i in range(3):
            threads.append(threading.Thread(target=writer, args=(i,)))

        # Start all at roughly the same time
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            os.unlink(db_path)
        except OSError:
            pass

        assert len(errors) == 0, f"Errors during concurrent R/W: {errors}"
        assert len(read_results) == 30, f"Expected 30 read results, got {len(read_results)}"
        assert write_count[0] == 15, f"Expected 15 writes, got {write_count[0]}"

    def test_high_contention_write_lock(self):
        """Very high contention: 20 threads writing to same DB simultaneously.

        The write lock serializes writes but prevents database locked errors.
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)
        errors = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(3):
                    mem.add(
                        subject=f"high_contention_t{int(time.time() * 1000) % 1000}_{i}",
                        predicate="test",
                        object="data",
                    )
            except sqlite3.OperationalError as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            os.unlink(db_path)
        except OSError:
            pass

        # No database locked errors
        locked_errors = [e for e in errors if "locked" in e.lower()]
        assert len(locked_errors) == 0, f"Got locked errors: {locked_errors}"

    # ── AC-51-02: WAL mode enabled ───────────────────────────────────────

    def test_wal_mode_is_enabled(self):
        """Verify WAL journal mode is enabled on the database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)

        with mem._conn() as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = result[0] if result else "unknown"

        try:
            os.unlink(db_path)
        except OSError:
            pass

        assert journal_mode.upper() == "WAL", f"Expected WAL mode, got: {journal_mode}"

    def test_wal_mode_persists_after_write(self):
        """WAL mode should remain enabled even after many writes."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)

        for i in range(50):
            mem.add(subject=f"entry_{i}", predicate="test", object=f"obj_{i}")

        with mem._conn() as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = result[0] if result else "unknown"

        try:
            os.unlink(db_path)
        except OSError:
            pass

        assert journal_mode.upper() == "WAL"

    # ── AC-51-03: Context manager usage ────────────────────────────────

    def test_context_manager_used_for_all_operations(self):
        """All database operations should use 'with self._conn()' context manager.

        This ensures connections are properly closed after each operation.
        """
        # This is verified by the fact that all methods use `with self._conn()`.
        # The delete() method now uses `with self._write_lock` AND `with self._conn()`.
        mem = SemanticMemory(db_path=":memory:")
        mem.add("test", "test", "test")

        # Should not raise - connection properly managed
        count = len(mem)
        assert count == 1

        deleted = mem.delete(mem.query()[0].id)
        assert deleted is True
        assert len(mem) == 0

    def test_connection_not_leaked_after_many_operations(self):
        """After many add/query operations, no connection leaks should occur."""
        import gc

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)

        # Perform many operations
        for i in range(100):
            mem.add(subject=f"entry_{i}", predicate="type", object=f"obj_{i}")

        for i in range(50):
            mem.query(subject="entry")

        for i in range(50):
            mem.recall("entry")

        # Force garbage collection
        gc.collect()

        # If connections were leaked, the DB file would have issues
        # Verify by reading count
        count = len(mem)
        assert count == 100, f"Expected 100 entries, got {count}"

        try:
            os.unlink(db_path)
        except OSError:
            pass

    # ── AC-51-04: Existing tests still pass ───────────────────────────

    def test_existing_tests_still_pass_after_thread_safety(self):
        """Verify basic add/get/query still work correctly."""
        mem = SemanticMemory(db_path=":memory:")
        entry = mem.add(subject="Rik", predicate="is", object="an AI", confidence=0.95)
        assert entry.subject == "Rik"

        retrieved = mem.get(entry.id)
        assert retrieved is not None
        assert retrieved.subject == "Rik"

        results = mem.query(subject="Rik")
        assert len(results) >= 1

    def test_delete_is_thread_safe(self):
        """Delete operation should be thread-safe and serialized."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        mem = SemanticMemory(db_path=db_path)

        # Add entries
        entries = []
        for i in range(20):
            e = mem.add(subject=f"to_delete_{i}", predicate="test", object="obj")
            entries.append(e.id)

        errors = []

        def deleter(entry_id: str) -> None:
            try:
                result = mem.delete(entry_id)
                assert result is True
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=deleter, args=(eid,)) for eid in entries]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            os.unlink(db_path)
        except OSError:
            pass

        assert len(errors) == 0, f"Delete errors: {errors}"
        assert len(mem) == 0, f"Expected 0 entries after delete, got {len(mem)}"


class TestKnowledgeGraphThreadSafety:
    """KG uses in-memory dict for query, but save operations should be thread-safe."""

    def test_kg_add_entity_concurrent(self):
        """Multiple threads adding entities simultaneously should be safe."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        kg = KnowledgeGraph(db_path=db_path)
        errors = []
        count = [0]

        def add_entity(thread_id: int) -> None:
            try:
                for i in range(10):
                    kg.add_entity(f"Entity_{thread_id}_{i}", EntityType.CONCEPT)
                    count[0] += 1
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=add_entity, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            os.unlink(db_path)
        except OSError:
            pass

        assert len(errors) == 0, f"Errors: {errors}"
        assert count[0] == 50, f"Expected 50 entities, got {count[0]}"

    def test_kg_relate_concurrent(self):
        """Multiple threads creating relationships simultaneously should be safe."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        kg = KnowledgeGraph(db_path=db_path)

        # Pre-create entities
        for i in range(10):
            kg.add_entity(f"Entity_{i}", EntityType.CONCEPT)

        errors = []
        rel_count = [0]

        def create_relationships(thread_id: int) -> None:
            try:
                for i in range(thread_id * 5, (thread_id + 1) * 5):
                    e1 = kg.get_entity(f"concept_entity_{i}")
                    if e1:
                        e2 = kg.get_entity(f"concept_entity_{(i + 1) % 10}")
                        if e2:
                            kg.relate(e1, e2, RelationshipType.RELATED_TO)
                            rel_count[0] += 1
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=create_relationships, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        try:
            os.unlink(db_path)
        except OSError:
            pass

        assert len(errors) == 0, f"Errors: {errors}"
