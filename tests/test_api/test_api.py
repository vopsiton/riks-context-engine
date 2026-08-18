"""Integration tests for the FastAPI server.

2026-08-19 stale-test cleanup (Vahit "onar" directive):
- Module-level skip removed: 9 routes exist (see app.routes); rewritten
  below against the current tenant-scoped /api/v1/* surface.
- Removed (routes no longer exist in server.py — legacy v0 API surface):
  /api/context/*, /api/memory/episodic|semantic|procedural/*,
  /api/graph/*, /api/tasks/*, /api/reflection/*.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

# ─── Health ───────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_ok(self, client: TestClient):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_models_listed(self, client: TestClient):
        res = client.get("/models")
        assert res.status_code == 200
        assert "models" in res.json()


# ─── Context Window (tenant-scoped) ───────────────────────────────────────────


class TestContextMessages:
    def test_add_message_user(self, client: TestClient):
        res = client.post(
            "/api/v1/context/messages",
            json={"role": "user", "content": "Hello, world!", "importance": 0.8},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "user"
        assert data["status"] == "added"
        assert "message_id" in data

    def test_add_message_assistant(self, client: TestClient):
        res = client.post(
            "/api/v1/context/messages",
            json={"role": "assistant", "content": "Hi there!", "importance": 0.5},
        )
        assert res.status_code == 200
        assert res.json()["role"] == "assistant"

    def test_add_message_invalid_role(self, client: TestClient):
        res = client.post(
            "/api/v1/context/messages",
            json={"role": "bot", "content": "I am not valid"},
        )
        assert res.status_code == 400  # server raises HTTPException for bad role

    def test_add_message_missing_content(self, client: TestClient):
        res = client.post(
            "/api/v1/context/messages",
            json={"role": "user"},
        )
        assert res.status_code == 422  # Pydantic validation error

    def test_add_message_importance_out_of_range(self, client: TestClient):
        res = client.post(
            "/api/v1/context/messages",
            json={"role": "user", "content": "test", "importance": -1.0},
        )
        assert res.status_code == 422

    def test_get_messages_default(self, client: TestClient):
        res = client.get(
            "/api/v1/context/messages",
            headers={"X-Tenant-Id": "tenant-msgtest"},
        )
        assert res.status_code == 200
        baseline = len(res.json())
        client.post(
            "/api/v1/context/messages",
            json={"role": "user", "content": "First"},
            headers={"X-Tenant-Id": "tenant-msgtest"},
        )
        client.post(
            "/api/v1/context/messages",
            json={"role": "assistant", "content": "Second"},
            headers={"X-Tenant-Id": "tenant-msgtest"},
        )
        res = client.get(
            "/api/v1/context/messages",
            headers={"X-Tenant-Id": "tenant-msgtest"},
        )
        messages = res.json()
        assert len(messages) == baseline + 2
        assert {m["role"] for m in messages[-2:]} == {"user", "assistant"}

    def test_get_messages_with_pruned(self, client: TestClient):
        client.post("/api/v1/context/messages", json={"role": "user", "content": "Keep"})
        # Add enough volume to force pruning of low-importance messages
        for _ in range(200):
            client.post(
                "/api/v1/context/messages",
                json={
                    "role": "user",
                    "content": "Lorem ipsum dolor sit amet " * 10,
                    "importance": 0.1,
                },
            )
        res = client.get("/api/v1/context/messages")
        assert res.status_code == 200
        # Pruned messages are excluded by default; some remain active
        assert len(res.json()) > 0

    def test_context_isolated_per_tenant(self, client: TestClient):
        """Tenant isolation (middleware scopes per header).

        Uses unique tenant ids: the per-tenant context registry is
        process-wide, so tenants shared with other test files (e.g.
        tenant-a/b in test_tenant_isolation.py) would leak state.
        """
        res_a = client.post(
            "/api/v1/context/messages",
            json={"role": "user", "content": "tenant A secret"},
            headers={"X-Tenant-Id": "tenant-iso-a"},
        )
        assert res_a.status_code == 200
        res_b = client.get(
            "/api/v1/context/messages",
            headers={"X-Tenant-Id": "tenant-iso-b"},
        )
        assert res_b.status_code == 200
        assert res_b.json() == []


class TestContextSummary:
    def test_summary_empty(self, client: TestClient):
        res = client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-empty"})
        assert res.status_code == 200
        data = res.json()
        for key in ("current_tokens", "max_tokens", "messages_count"):
            assert key in data
        assert data["messages_count"] == 0

    def test_summary_after_messages(self, client: TestClient):
        tenant = {"X-Tenant-Id": "tenant-summary"}
        before = client.get("/api/v1/context/summary", headers=tenant).json()["messages_count"]
        client.post(
            "/api/v1/context/messages", json={"role": "user", "content": "Hello"}, headers=tenant
        )
        client.post(
            "/api/v1/context/messages",
            json={"role": "assistant", "content": "Hi"},
            headers=tenant,
        )
        res = client.get("/api/v1/context/summary", headers=tenant)
        assert res.status_code == 200
        assert res.json()["messages_count"] == before + 2


class TestTenantValidation:
    def test_missing_tenant_header_401(self, client: TestClient):
        res = client.post(
            "/api/v1/context/messages",
            json={"role": "user", "content": "hi"},
            headers={"X-Tenant-Id": ""},  # empty -> 401 per middleware contract
        )
        assert res.status_code == 401


# ─── Memory Export / Import ───────────────────────────────────────────────────


class TestMemoryExport:
    def test_export_json(self, client: TestClient):
        res = client.get("/api/v1/memory/export", params={"format": "json"})
        assert res.status_code == 200
        data = res.json()
        assert data["schema_version"]
        assert "export_id" in data
        # `data` is the serialized manifest; must parse as JSON
        parsed = json.loads(data["data"])
        assert "episodic" in parsed

    def test_export_yaml(self, client: TestClient):
        res = client.get("/api/v1/memory/export", params={"format": "yaml"})
        assert res.status_code == 200
        assert "export_id" in res.json()

    def test_export_invalid_format_422(self, client: TestClient):
        res = client.get("/api/v1/memory/export", params={"format": "toml"})
        assert res.status_code == 422


class TestMemoryImport:
    def test_import_roundtrip(self, client: TestClient):
        export_res = client.get("/api/v1/memory/export", params={"format": "json"})
        assert export_res.status_code == 200
        res = client.post(
            "/api/v1/memory/import",
            json={"content": export_res.json()["data"], "format": "json", "merge": True},
        )
        assert res.status_code == 200
        assert "imported" in res.json()

    def test_import_invalid_content_400(self, client: TestClient):
        res = client.post(
            "/api/v1/memory/import",
            json={"content": "{not valid json", "format": "json"},
        )
        assert res.status_code == 400

    def test_import_missing_content_422(self, client: TestClient):
        res = client.post("/api/v1/memory/import", json={"format": "json"})
        assert res.status_code == 422
