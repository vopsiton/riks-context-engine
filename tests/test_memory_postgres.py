"""Tests for the PostgreSQL-backed semantic memory store.

Requires a reachable PostgreSQL instance via TEST_POSTGRES_DSN. Skipped
automatically when that isn't set (e.g. no local Postgres) or when the
`postgres` extra isn't installed. CI provides a postgres service
container and sets TEST_POSTGRES_DSN so these run for real there.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from riks_context_engine.memory.postgres import PostgresSemanticMemory  # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not DSN, reason="TEST_POSTGRES_DSN not set; skipping PostgreSQL integration tests"
)


@pytest.fixture
def mem():
    store = PostgresSemanticMemory(dsn=DSN)
    yield store
    with store._conn.cursor() as cur:
        cur.execute("DELETE FROM semantic_entries")


class TestPostgresSemanticMemory:
    def test_add_entry(self, mem):
        entry = mem.add(subject="Rik", predicate="is", object="an AI assistant", confidence=0.95)
        assert entry.subject == "Rik"
        assert entry.predicate == "is"
        assert entry.confidence == 0.95

    def test_get_increments_access_count(self, mem):
        entry = mem.add("Vahit", "works at", "opsiton")
        assert entry.access_count == 0

        fetched = mem.get(entry.id)
        assert fetched is not None
        assert fetched.access_count == 1
        assert fetched.last_accessed is not None

    def test_get_returns_none_for_missing(self, mem):
        assert mem.get("nonexistent") is None

    def test_query_by_subject(self, mem):
        mem.add("auth_service", "uses", "JWT")
        mem.add("billing_service", "uses", "Stripe")

        results = mem.query(subject="auth")
        assert len(results) == 1
        assert results[0].subject == "auth_service"

    def test_query_by_predicate(self, mem):
        mem.add("auth_service", "uses", "JWT")
        mem.add("billing_service", "depends_on", "auth_service")

        results = mem.query(predicate="uses")
        assert len(results) == 1
        assert results[0].predicate == "uses"

    def test_query_by_subject_and_predicate(self, mem):
        mem.add("auth_service", "uses", "JWT")
        mem.add("auth_service", "owned_by", "platform_team")

        results = mem.query(subject="auth", predicate="uses")
        assert len(results) == 1
        assert results[0].object == "JWT"

    def test_query_returns_all_when_no_filters(self, mem):
        mem.add("a", "b", "c")
        mem.add("d", "e", "f")

        assert len(mem.query()) == 2

    def test_query_escapes_like_wildcards(self, mem):
        mem.add("100%_done", "status", "complete")
        mem.add("other", "status", "pending")

        results = mem.query(subject="100%_done")
        assert len(results) == 1
        assert results[0].subject == "100%_done"

    def test_recall_keyword_match(self, mem):
        mem.add("Rik", "is", "an AI assistant")
        mem.add("Vahit", "works at", "opsiton")

        results = mem.recall("opsiton")
        assert len(results) == 1
        assert results[0].subject == "Vahit"

    def test_recall_no_match_returns_empty(self, mem):
        mem.add("Rik", "is", "an AI assistant")
        assert mem.recall("xyzzy_not_found") == []

    def test_embedding_round_trip(self, mem):
        entry = mem.add("x", "y", "z", embedding=[0.1, 0.2, 0.3])
        fetched = mem.get(entry.id)
        assert fetched is not None
        assert fetched.embedding == [0.1, 0.2, 0.3]

    def test_delete_returns_true_and_removes(self, mem):
        entry = mem.add("temp", "fact", "value")
        assert len(mem) == 1

        assert mem.delete(entry.id) is True
        assert len(mem) == 0

    def test_delete_returns_false_for_missing(self, mem):
        assert mem.delete("nonexistent") is False

    def test_len(self, mem):
        assert len(mem) == 0
        mem.add("a", "b", "c")
        assert len(mem) == 1
        mem.add("d", "e", "f")
        assert len(mem) == 2

    def test_to_memory_entry(self, mem):
        from riks_context_engine.memory.base import MemoryType

        entry = mem.add("auth_service", "uses", "JWT RS256", confidence=0.9)
        generic = mem.to_memory_entry(entry)

        assert generic.type == MemoryType.SEMANTIC
        assert generic.content == "auth_service uses JWT RS256"
        assert generic.importance == 0.9
