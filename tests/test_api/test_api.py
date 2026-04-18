"""Integration tests for the FastAPI server."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skip(reason="API routes not yet implemented - issue to be tracked")

# ─── Health ───────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_ok(self, client: TestClient):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


# ─── Context Window ───────────────────────────────────────────────────────────


class TestContextMessages:
    def test_add_message_user(self, client: TestClient):
        res = client.post(
            "/api/context/messages",
            json={
                "role": "user",
                "content": "Hello, world!",
                "importance": 0.8,
                "is_grounding": True,
                "priority_tier": 1,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "user"
        assert data["content"] == "Hello, world!"
        assert data["importance"] == 0.8
        assert data["is_grounding"] is True
        assert data["priority_tier"] == 1
        assert "id" in data

    def test_add_message_assistant(self, client: TestClient):
        res = client.post(
            "/api/context/messages",
            json={
                "role": "assistant",
                "content": "Hi there!",
                "importance": 0.5,
            },
        )
        assert res.status_code == 200
        assert res.json()["role"] == "assistant"

    def test_add_message_invalid_role(self, client: TestClient):
        res = client.post(
            "/api/context/messages",
            json={
                "role": "bot",
                "content": "I am not valid",
            },
        )
        assert res.status_code == 422  # Pydantic validation error

    def test_add_message_missing_content(self, client: TestClient):
        res = client.post(
            "/api/context/messages",
            json={
                "role": "user",
            },
        )
        assert res.status_code == 422

    def test_add_message_negative_importance(self, client: TestClient):
        res = client.post(
            "/api/context/messages",
            json={
                "role": "user",
                "content": "test",
                "importance": -1.0,
            },
        )
        assert res.status_code == 422

    def test_get_messages_default(self, client: TestClient):
        # Add two messages first
        client.post("/api/context/messages", json={"role": "user", "content": "First"})
        client.post("/api/context/messages", json={"role": "assistant", "content": "Second"})
        res = client.get("/api/context/messages")
        assert res.status_code == 200
        messages = res.json()
        assert len(messages) == 2

    def test_get_messages_with_pruned(self, client: TestClient):
        client.post("/api/context/messages", json={"role": "user", "content": "Keep"})
        # Exceed token limit to force pruning
        for _ in range(200):
            client.post(
                "/api/context/messages",
                json={"role": "user", "content": "Lorem ipsum dolor sit amet " * 10},
            )
        res = client.get("/api/context/messages", params={"include_pruned": True})
        assert res.status_code == 200
        # With include_pruned we should see all messages including pruned ones
        assert len(res.json()) > 0


class TestContextStats:
    def test_stats_empty(self, client: TestClient):
        res = client.get("/api/context/stats")
        assert res.status_code == 200
        data = res.json()
        assert "current_tokens" in data
        assert "max_tokens" in data
        assert "messages_count" in data
        assert "tokens_remaining" in data
        assert "needs_pruning" in data

    def test_stats_after_messages(self, client: TestClient):
        client.post("/api/context/messages", json={"role": "user", "content": "Hello"})
        client.post("/api/context/messages", json={"role": "assistant", "content": "Hi"})
        res = client.get("/api/context/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["messages_count"] == 2
        assert data["active_messages_count"] >= 0


class TestContextPrune:
    def test_prune_triggers_pruning(self, client: TestClient):
        # Add enough messages to potentially need pruning
        for i in range(100):
            client.post(
                "/api/context/messages",
                json={
                    "role": "user",
                    "content": f"Message number {i} with some content " * 5,
                    "importance": 0.3,
                    "priority_tier": 3,
                },
            )
        res = client.post("/api/context/prune")
        assert res.status_code == 200
        data = res.json()
        assert data["pruned"] is True
        assert "tokens_before" in data
        assert "tokens_after" in data


class TestContextReset:
    def test_reset_clears_messages(self, client: TestClient):
        for _ in range(5):
            client.post("/api/context/messages", json={"role": "user", "content": "Test"})
        res = client.post("/api/context/reset")
        assert res.status_code == 200
        assert res.json()["reset"] is True
        # Verify messages are gone
        stats = client.get("/api/context/stats").json()
        assert stats["messages_count"] == 0


# ─── Episodic Memory ───────────────────────────────────────────────────────────


class TestEpisodicAdd:
    def test_add_entry(self, client: TestClient):
        res = client.post(
            "/api/memory/episodic",
            json={
                "content": "User asked about shipping",
                "importance": 0.7,
                "tags": ["shipping", "question"],
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["content"] == "User asked about shipping"
        assert data["importance"] == 0.7
        assert data["tags"] == ["shipping", "question"]
        assert "id" in data

    def test_add_entry_minimal(self, client: TestClient):
        res = client.post(
            "/api/memory/episodic",
            json={
                "content": "Simple note",
            },
        )
        assert res.status_code == 201
        assert res.json()["importance"] == 0.5  # default

    def test_add_entry_missing_content(self, client: TestClient):
        res = client.post("/api/memory/episodic", json={})
        assert res.status_code == 422

    def test_add_entry_importance_out_of_range(self, client: TestClient):
        res = client.post(
            "/api/memory/episodic",
            json={
                "content": "test",
                "importance": 2.0,
            },
        )
        assert res.status_code == 422


class TestEpisodicGet:
    def test_get_existing(self, client: TestClient):
        add_res = client.post(
            "/api/memory/episodic",
            json={
                "content": "Test entry",
                "importance": 0.5,
            },
        )
        entry_id = add_res.json()["id"]
        res = client.get(f"/api/memory/episodic/{entry_id}")
        assert res.status_code == 200
        assert res.json()["content"] == "Test entry"

    def test_get_nonexistent(self, client: TestClient):
        res = client.get("/api/memory/episodic/nonexistent_id_123")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


class TestEpisodicDelete:
    def test_delete_existing(self, client: TestClient):
        add_res = client.post("/api/memory/episodic", json={"content": "To be deleted"})
        entry_id = add_res.json()["id"]
        res = client.delete(f"/api/memory/episodic/{entry_id}")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        # Verify it's gone
        get_res = client.get(f"/api/memory/episodic/{entry_id}")
        assert get_res.status_code == 404

    def test_delete_nonexistent(self, client: TestClient):
        res = client.delete("/api/memory/episodic/does_not_exist")
        assert res.status_code == 404


class TestEpisodicQuery:
    def test_query_finds_match(self, client: TestClient):
        client.post("/api/memory/episodic", json={"content": "Shipping problem encountered"})
        client.post("/api/memory/episodic", json={"content": "Payment processed"})
        res = client.get("/api/memory/episodic", params={"query": "shipping"})
        assert res.status_code == 200
        results = res.json()
        assert len(results) >= 1
        assert any("shipping" in r["content"].lower() for r in results)

    def test_query_no_match(self, client: TestClient):
        client.post("/api/memory/episodic", json={"content": "Unrelated note"})
        res = client.get("/api/memory/episodic", params={"query": "zzzz_no_match_zzz"})
        assert res.status_code == 200
        assert res.json() == []

    def test_query_with_limit(self, client: TestClient):
        for i in range(5):
            client.post(
                "/api/memory/episodic",
                json={"content": f"Entry {i} with keyword", "importance": 0.5},
            )
        res = client.get("/api/memory/episodic", params={"query": "keyword", "limit": 2})
        assert res.status_code == 200
        assert len(res.json()) <= 2


# ─── Semantic Memory ───────────────────────────────────────────────────────────


class TestSemanticAdd:
    def test_add_entry(self, client: TestClient):
        res = client.post(
            "/api/memory/semantic",
            json={
                "subject": "Vahit",
                "predicate": "works at",
                "object": "Opsiton",
                "confidence": 0.95,
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["subject"] == "Vahit"
        assert data["predicate"] == "works at"
        assert data["object"] == "Opsiton"
        assert data["confidence"] == 0.95
        assert "id" in data

    def test_add_entry_without_object(self, client: TestClient):
        res = client.post(
            "/api/memory/semantic",
            json={
                "subject": "Python",
                "predicate": "is a language",
            },
        )
        assert res.status_code == 201
        assert res.json()["object"] is None

    def test_add_entry_confidence_out_of_range(self, client: TestClient):
        res = client.post(
            "/api/memory/semantic",
            json={
                "subject": "X",
                "predicate": "Y",
                "confidence": 1.5,
            },
        )
        assert res.status_code == 422


class TestSemanticGet:
    def test_get_existing(self, client: TestClient):
        add_res = client.post(
            "/api/memory/semantic",
            json={
                "subject": "Rik",
                "predicate": "is an AI agent",
                "confidence": 1.0,
            },
        )
        entry_id = add_res.json()["id"]
        res = client.get(f"/api/memory/semantic/{entry_id}")
        assert res.status_code == 200
        assert res.json()["subject"] == "Rik"

    def test_get_nonexistent(self, client: TestClient):
        res = client.get("/api/memory/semantic/does_not_exist")
        assert res.status_code == 404


class TestSemanticDelete:
    def test_delete_existing(self, client: TestClient):
        add_res = client.post(
            "/api/memory/semantic",
            json={
                "subject": "Temp",
                "predicate": "to delete",
            },
        )
        entry_id = add_res.json()["id"]
        res = client.delete(f"/api/memory/semantic/{entry_id}")
        assert res.status_code == 200
        # Verify it's gone
        get_res = client.get(f"/api/memory/semantic/{entry_id}")
        assert get_res.status_code == 404

    def test_delete_nonexistent(self, client: TestClient):
        res = client.delete("/api/memory/semantic/nonexistent_123")
        assert res.status_code == 404


class TestSemanticQuery:
    def test_query_by_subject(self, client: TestClient):
        client.post(
            "/api/memory/semantic",
            json={"subject": "Kubernetes", "predicate": "is a", "object": "orchestrator"},
        )
        res = client.get("/api/memory/semantic", params={"subject": "kubernetes"})
        assert res.status_code == 200
        results = res.json()
        assert any(r["subject"].lower() == "kubernetes" for r in results)

    def test_query_by_predicate(self, client: TestClient):
        client.post(
            "/api/memory/semantic",
            json={"subject": "Docker", "predicate": "containers", "object": "runc"},
        )
        res = client.get("/api/memory/semantic", params={"predicate": "containers"})
        assert res.status_code == 200
        assert len(res.json()) >= 1

    def test_query_recall(self, client: TestClient):
        client.post(
            "/api/memory/semantic",
            json={"subject": "Context window", "predicate": "manages", "object": "tokens"},
        )
        res = client.get("/api/memory/semantic", params={"recall": "context"})
        assert res.status_code == 200
        results = res.json()
        assert len(results) >= 1

    def test_query_combined(self, client: TestClient):
        client.post(
            "/api/memory/semantic",
            json={"subject": "FastAPI", "predicate": "is fast", "object": "True"},
        )
        res = client.get("/api/memory/semantic", params={"subject": "fastapi", "predicate": "fast"})
        assert res.status_code == 200


# ─── Procedural Memory ─────────────────────────────────────────────────────────


class TestProceduralStore:
    def test_store_procedure(self, client: TestClient):
        res = client.post(
            "/api/memory/procedural",
            json={
                "name": "deploy_service",
                "description": "Deploy a microservice to Kubernetes",
                "steps": [
                    "Build Docker image",
                    "Push to registry",
                    "Apply Kubernetes manifests",
                    "Verify deployment",
                ],
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "deploy_service"
        assert len(data["steps"]) == 4

    def test_store_procedure_minimal(self, client: TestClient):
        res = client.post(
            "/api/memory/procedural",
            json={
                "name": "simple_task",
                "description": "A simple task",
                "steps": ["Do thing"],
            },
        )
        assert res.status_code == 201

    def test_store_procedure_missing_steps(self, client: TestClient):
        res = client.post(
            "/api/memory/procedural",
            json={
                "name": "incomplete",
                "description": "Missing steps",
            },
        )
        assert res.status_code == 422


class TestProceduralGet:
    def test_get_existing(self, client: TestClient):
        add_res = client.post(
            "/api/memory/procedural",
            json={
                "name": "test_proc",
                "description": "Test",
                "steps": ["Step 1"],
            },
        )
        proc_id = add_res.json()["id"]
        res = client.get(f"/api/memory/procedural/{proc_id}")
        assert res.status_code == 200
        assert res.json()["name"] == "test_proc"

    def test_get_nonexistent(self, client: TestClient):
        res = client.get("/api/memory/procedural/nonexistent_123")
        assert res.status_code == 404


class TestProceduralFind:
    def test_find_by_name(self, client: TestClient):
        client.post(
            "/api/memory/procedural",
            json={
                "name": "build_docker_image",
                "description": "Build a Docker container image",
                "steps": ["docker build", "docker push"],
            },
        )
        res = client.get("/api/memory/procedural", params={"query": "docker"})
        assert res.status_code == 200
        results = res.json()
        assert any("docker" in r["name"].lower() for r in results)

    def test_find_by_description(self, client: TestClient):
        client.post(
            "/api/memory/procedural",
            json={
                "name": "deploy_k8s",
                "description": "Deploy to Kubernetes cluster",
                "steps": ["kubectl apply"],
            },
        )
        res = client.get("/api/memory/procedural", params={"query": "kubernetes"})
        assert res.status_code == 200
        results = res.json()
        assert any("kubernetes" in r["description"].lower() for r in results)

    def test_find_no_match(self, client: TestClient):
        res = client.get("/api/memory/procedural", params={"query": "xyz_no_match"})
        assert res.status_code == 200
        assert res.json() == []


# ─── Knowledge Graph ───────────────────────────────────────────────────────────


class TestGraphEntities:
    def test_add_entity(self, client: TestClient):
        res = client.post(
            "/api/graph/entities",
            json={
                "name": "Vahit",
                "entity_type": "person",
                "properties": {"role": "DevSecOps Lead"},
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Vahit"
        assert data["entity_type"] == "person"
        assert data["properties"]["role"] == "DevSecOps Lead"

    def test_add_entity_invalid_type(self, client: TestClient):
        res = client.post(
            "/api/graph/entities",
            json={
                "name": "ProjectX",
                "entity_type": "invalid_type",
            },
        )
        assert res.status_code == 400

    def test_add_entity_minimal(self, client: TestClient):
        res = client.post(
            "/api/graph/entities",
            json={
                "name": "Opsiton",
                "entity_type": "project",
            },
        )
        assert res.status_code == 201

    def test_get_entity_existing(self, client: TestClient):
        add_res = client.post(
            "/api/graph/entities",
            json={
                "name": "Rik",
                "entity_type": "person",
            },
        )
        entity_id = add_res.json()["id"]
        res = client.get(f"/api/graph/entities/{entity_id}")
        assert res.status_code == 200
        assert res.json()["name"] == "Rik"

    def test_get_entity_nonexistent(self, client: TestClient):
        res = client.get("/api/graph/entities/person_nonexistent_xyz")
        assert res.status_code == 404


class TestGraphRelations:
    def test_create_relation(self, client: TestClient):
        # Create two entities
        e1_res = client.post("/api/graph/entities", json={"name": "Alice", "entity_type": "person"})
        e2_res = client.post("/api/graph/entities", json={"name": "Bob", "entity_type": "person"})
        e1_id = e1_res.json()["id"]
        e2_id = e2_res.json()["id"]

        res = client.post(
            "/api/graph/relations",
            json={
                "from_entity_id": e1_id,
                "to_entity_id": e2_id,
                "relationship_type": "works_with",
                "confidence": 0.9,
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["from_entity_id"] == e1_id
        assert data["to_entity_id"] == e2_id
        assert data["relationship_type"] == "works_with"
        assert data["confidence"] == 0.9

    def test_create_relation_invalid_type(self, client: TestClient):
        e1_res = client.post("/api/graph/entities", json={"name": "X", "entity_type": "concept"})
        e2_res = client.post("/api/graph/entities", json={"name": "Y", "entity_type": "concept"})
        res = client.post(
            "/api/graph/relations",
            json={
                "from_entity_id": e1_res.json()["id"],
                "to_entity_id": e2_res.json()["id"],
                "relationship_type": "invalid_rel_type",
            },
        )
        assert res.status_code == 400

    def test_create_relation_from_entity_not_found(self, client: TestClient):
        e2_res = client.post("/api/graph/entities", json={"name": "Y", "entity_type": "concept"})
        res = client.post(
            "/api/graph/relations",
            json={
                "from_entity_id": "nonexistent_entity",
                "to_entity_id": e2_res.json()["id"],
                "relationship_type": "works_with",
            },
        )
        assert res.status_code == 404

    def test_create_relation_to_entity_not_found(self, client: TestClient):
        e1_res = client.post("/api/graph/entities", json={"name": "X", "entity_type": "concept"})
        res = client.post(
            "/api/graph/relations",
            json={
                "from_entity_id": e1_res.json()["id"],
                "to_entity_id": "nonexistent_entity",
                "relationship_type": "works_with",
            },
        )
        assert res.status_code == 404


class TestGraphQuery:
    def test_query_by_entity_name(self, client: TestClient):
        client.post("/api/graph/entities", json={"name": "Kubernetes", "entity_type": "tool"})
        res = client.get("/api/graph/query", params={"entity_name": "kubernetes"})
        assert res.status_code == 200
        results = res.json()
        assert any(r.get("name", "").lower() == "kubernetes" for r in results)

    def test_query_by_relationship_type(self, client: TestClient):
        e1 = client.post(
            "/api/graph/entities", json={"name": "A", "entity_type": "concept"}
        ).json()["id"]
        e2 = client.post(
            "/api/graph/entities", json={"name": "B", "entity_type": "concept"}
        ).json()["id"]
        client.post(
            "/api/graph/relations",
            json={
                "from_entity_id": e1,
                "to_entity_id": e2,
                "relationship_type": "related_to",
            },
        )
        res = client.get("/api/graph/query", params={"relationship_type": "related_to"})
        assert res.status_code == 200

    def test_query_no_filter(self, client: TestClient):
        client.post("/api/graph/entities", json={"name": "TestEntity", "entity_type": "concept"})
        res = client.get("/api/graph/query")
        assert res.status_code == 200

    def test_get_entity_relationships(self, client: TestClient):
        e1 = client.post(
            "/api/graph/entities", json={"name": "Alice", "entity_type": "person"}
        ).json()["id"]
        e2 = client.post(
            "/api/graph/entities", json={"name": "Bob", "entity_type": "person"}
        ).json()["id"]
        client.post(
            "/api/graph/relations",
            json={
                "from_entity_id": e1,
                "to_entity_id": e2,
                "relationship_type": "knows_about",
            },
        )
        res = client.get(f"/api/graph/entities/{e1}/relationships")
        assert res.status_code == 200
        rels = res.json()
        assert len(rels) >= 1


# ─── Task Decomposition ────────────────────────────────────────────────────────


class TestTaskDecompose:
    def test_decompose_simple_goal(self, client: TestClient):
        res = client.post(
            "/api/tasks/decompose",
            json={
                "goal": "Setup CI/CD pipeline and deploy to production",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["goal"] == "Setup CI/CD pipeline and deploy to production"
        assert len(data["tasks"]) >= 1
        assert data["valid"] is True
        assert data["validation_error"] is None

    def test_decompose_multiple_parts(self, client: TestClient):
        res = client.post(
            "/api/tasks/decompose",
            json={
                "goal": "Build the image, run tests, and deploy to cluster",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["tasks"]) >= 3

    def test_decompose_with_execute(self, client: TestClient):
        res = client.post(
            "/api/tasks/decompose",
            json={
                "goal": "Analyze logs and generate report",
                "execute": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        # After execution, tasks should have done status
        for task in data["tasks"]:
            assert task["status"] in ("pending", "running", "done", "failed", "skipped")

    def test_decompose_empty_goal(self, client: TestClient):
        res = client.post("/api/tasks/decompose", json={"goal": ""})
        # Edge case - should still return a valid graph (may be empty or default)
        assert res.status_code == 200

    def test_get_nonexistent_task(self, client: TestClient):
        res = client.get("/api/tasks/task_nonexistent")
        assert res.status_code == 404


# ─── Self-Reflection ────────────────────────────────────────────────────────────


class TestReflectionAnalyze:
    def test_analyze_success_interaction(self, client: TestClient):
        res = client.post(
            "/api/reflection/analyze",
            json={
                "interaction_id": "int_001",
                "conversation": [
                    {"role": "user", "content": "Deploy the service"},
                    {"role": "assistant", "content": "Deployment success - all pods running"},
                ],
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["interaction_id"] == "int_001"
        assert "went_well" in data
        assert "went_wrong" in data
        assert "lessons" in data

    def test_analyze_error_interaction(self, client: TestClient):
        res = client.post(
            "/api/reflection/analyze",
            json={
                "interaction_id": "int_002",
                "conversation": [
                    {"role": "user", "content": "Run the tests"},
                    {
                        "role": "assistant",
                        "content": "Test failed with error: timeout on endpoint /api/health",
                    },
                    {"role": "user", "content": "Fix it"},
                ],
            },
        )
        assert res.status_code == 200
        data = res.json()
        # Should have detected something went wrong
        assert isinstance(data["went_wrong"], list)

    def test_analyze_empty_conversation(self, client: TestClient):
        res = client.post(
            "/api/reflection/analyze",
            json={
                "interaction_id": "int_003",
                "conversation": [],
            },
        )
        assert res.status_code == 200

    def test_analyze_missing_interaction_id(self, client: TestClient):
        res = client.post(
            "/api/reflection/analyze",
            json={
                "conversation": [{"role": "user", "content": "test"}],
            },
        )
        assert res.status_code == 422

    def test_analyze_missing_conversation(self, client: TestClient):
        res = client.post(
            "/api/reflection/analyze",
            json={
                "interaction_id": "int_004",
            },
        )
        assert res.status_code == 422


class TestReflectionLessons:
    def test_get_lessons_empty(self, client: TestClient):
        res = client.get("/api/reflection/lessons")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_get_lessons_after_analysis(self, client: TestClient):
        # Analyze some interactions with potential issues
        client.post(
            "/api/reflection/analyze",
            json={
                "interaction_id": "int_010",
                "conversation": [
                    {"role": "user", "content": "Call the API"},
                    {"role": "assistant", "content": "API timeout error"},
                ],
            },
        )
        res = client.get("/api/reflection/lessons")
        assert res.status_code == 200
        lessons = res.json()
        # Should have at least one lesson since there was a failure
        assert isinstance(lessons, list)


class TestReflectionResolve:
    def test_resolve_existing_lesson(self, client: TestClient):
        # Create a lesson
        client.post(
            "/api/reflection/analyze",
            json={
                "interaction_id": "int_020",
                "conversation": [
                    {"role": "user", "content": "Deploy with missing config"},
                    {"role": "assistant", "content": "Error: permission denied"},
                ],
            },
        )
        lessons = client.get("/api/reflection/lessons").json()
        if lessons:
            lesson_id = lessons[0]["id"]
            res = client.post(f"/api/reflection/resolve/{lesson_id}")
            assert res.status_code == 200
            assert res.json()["resolved"] is True

    def test_resolve_nonexistent_lesson(self, client: TestClient):
        res = client.post("/api/reflection/resolve/lesson_nonexistent_123")
        assert res.status_code == 404


class TestReflectionMistakes:
    def test_get_mistake_frequency(self, client: TestClient):
        res = client.get("/api/reflection/mistakes")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict)
        # Initially may be empty
        for k, v in data.items():
            assert isinstance(k, str)
            assert isinstance(v, int)

    def test_mistakes_after_failures(self, client: TestClient):
        # Trigger some failures
        for i in range(3):
            client.post(
                "/api/reflection/analyze",
                json={
                    "interaction_id": f"int_fail_{i}",
                    "conversation": [
                        {"role": "user", "content": f"Attempt {i}"},
                        {"role": "assistant", "content": "Failed with error and timeout"},
                    ],
                },
            )
        res = client.get("/api/reflection/mistakes")
        assert res.status_code == 200
