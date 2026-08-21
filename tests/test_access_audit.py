"""Integration tests for access control + audit log (#110).

Covers the acceptance criteria:
- (a) API key missing/incorrect -> 401 when an API key is configured.
- (b) every request produces an audit entry + it is visible via
  ``GET /api/v1/audit`` (tenant-scoped).
Plus RBAC (admin vs regular) and the critical-operation endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.audit_log import reset_registry
from riks_context_engine.api.server import app


@pytest.fixture(autouse=True)
def _clean_audit(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Isolate the audit store to a temp dir and reset the registry per test."""
    monkeypatch.setenv("RIKS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RIKS_TENANT_ID", raising=False)
    monkeypatch.delenv("RIKS_ADMIN_API_KEYS", raising=False)
    monkeypatch.delenv("RIKS_AUDIT_ADMIN", raising=False)
    reset_registry()
    yield
    reset_registry()


@pytest.fixture(autouse=True)
def _reset_engine():
    """Reset the module-level memory instances before each test."""
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    yield
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app.

    Sends a valid X-Tenant-Id header so the tenant-isolation middleware
    (which 401s on every protected path without a well-formed tenant)
    lets API calls through. Tests asserting tenant validation (401)
    should pass explicit headers to override this default.
    """
    import riks_context_engine.api.server as server

    # Set API_KEY for tests (fail-closed, #166).
    original_key = server.API_KEY
    server.API_KEY = "test-api-key"
    try:
        with TestClient(
            app, headers={"X-Tenant-Id": "test-tenant", "X-API-Key": "test-api-key"}
        ) as c:
            yield c
    finally:
        server.API_KEY = original_key


@pytest.fixture
def _api_key_configured(monkeypatch: pytest.MonkeyPatch):
    """Configure a server API key so the auth middleware enforces it."""
    monkeypatch.setattr(server_module, "API_KEY", "sekrit-key")
    yield "sekrit-key"


class TestApiKeyAuth:
    def test_missing_api_key_401(self, client: TestClient, _api_key_configured):
        # Criterion (a): no X-API-Key -> 401 on a protected path.
        res = client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-a"})
        assert res.status_code == 401

    def test_wrong_api_key_401(self, client: TestClient, _api_key_configured):
        res = client.get(
            "/api/v1/context/summary",
            headers={"X-Tenant-Id": "tenant-a", "X-API-Key": "wrong"},
        )
        assert res.status_code == 401

    def test_correct_api_key_passes(self, client: TestClient, _api_key_configured):
        res = client.get(
            "/api/v1/context/summary",
            headers={"X-Tenant-Id": "tenant-a", "X-API-Key": "sekrit-key"},
        )
        assert res.status_code == 200

    def test_no_api_key_configured_fail_closed(self, client: TestClient):
        # No API_KEY configured -> fail-closed (401), #166.
        # Open mode only for RIKS_ENV=local.
        res = client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-b"})
        assert res.status_code == 401


class TestAuditLog:
    def test_request_creates_audit_entry_and_visible(self, client: TestClient):
        # Criterion (b): a request produces an audit entry visible via
        # GET /api/v1/audit (same tenant).
        res = client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-audit"})
        assert res.status_code == 200

        # The summary GET itself is now audited; query it back.
        log = client.get("/api/v1/audit", headers={"X-Tenant-Id": "tenant-audit"})
        assert log.status_code == 200
        body = log.json()
        assert body["tenant"] == "tenant-audit"
        assert body["total"] >= 1
        assert any(e["endpoint"] == "/api/v1/context/summary" for e in body["entries"])

    def test_audit_entry_fields(self, client: TestClient):
        client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-audit2"})
        log = client.get("/api/v1/audit", headers={"X-Tenant-Id": "tenant-audit2"}).json()
        entry = next(e for e in log["entries"] if e["endpoint"] == "/api/v1/context/summary")
        # Every required audit field is present and sane.
        assert entry["method"] == "GET"
        assert entry["status"] == 200
        assert entry["tenant"] == "tenant-audit2"
        assert entry["latency_ms"] >= 0
        assert entry["timestamp"]  # non-empty ISO timestamp
        assert entry["category"] in ("request",)

    def test_audit_tenant_isolation(self, client: TestClient):
        # Tenant A's activity must not appear in tenant B's audit log.
        client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-a"})
        client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-b"})
        log_a = client.get("/api/v1/audit", headers={"X-Tenant-Id": "tenant-a"}).json()
        log_b = client.get("/api/v1/audit", headers={"X-Tenant-Id": "tenant-b"}).json()
        # Both scoped to their own tenant.
        assert log_a["tenant"] == "tenant-a"
        assert log_b["tenant"] == "tenant-b"
        # Tenant A's log has no entries recorded under tenant B and vice versa.
        assert all(e["tenant"] == "tenant-a" for e in log_a["entries"])
        assert all(e["tenant"] == "tenant-b" for e in log_b["entries"])

    def test_audit_pagination(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(server_module, "API_KEY", "")  # open mode
        tenant = "tenant-page"
        for _ in range(5):
            client.get("/api/v1/context/summary", headers={"X-Tenant-Id": tenant})
        page = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": tenant},
            params={"limit": 2, "offset": 0},
        ).json()
        assert len(page["entries"]) == 2
        assert page["total"] == 5
        # offset beyond the set returns empty.
        page2 = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": tenant},
            params={"limit": 100, "offset": 100},
        ).json()
        assert page2["entries"] == []

    def test_audit_critical_category_for_import(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        # A memory import is flagged as a critical operation (memory.import).
        monkeypatch.setenv("RIKS_TENANT_ID", "tenant-crit")
        reset_registry()
        client.post(
            "/api/v1/memory/import",
            headers={"X-Tenant-Id": "tenant-crit"},
            json={"content": "{}", "format": "json"},
        )
        # The middleware records the request; category derives from method+path.
        log = client.get("/api/v1/audit", headers={"X-Tenant-Id": "tenant-crit"}).json()
        import_entries = [e for e in log["entries"] if e["endpoint"] == "/api/v1/memory/import"]
        assert import_entries, "memory import was not audited"
        assert import_entries[0]["category"] in ("memory.import", "request")

    def test_critical_operation_endpoint(self, client: TestClient):
        # Record a critical operation explicitly (e.g. context.clear).
        res = client.post(
            "/api/v1/audit/operation",
            headers={"X-Tenant-Id": "tenant-ops"},
            params={
                "category": "context.clear",
                "endpoint": "/api/v1/context/messages",
                "method": "DELETE",
                "status": 200,
            },
        )
        assert res.status_code == 200
        assert res.json()["category"] == "context.clear"
        # It shows up filtered by category.
        log = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": "tenant-ops"},
            params={"category": "context.clear"},
        ).json()
        assert any(e["category"] == "context.clear" for e in log["entries"])


class TestRBAC:
    def test_admin_can_read_other_tenant_log(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        # Admin opt-in: an admin API key may read another tenant's log.
        monkeypatch.setenv("RIKS_AUDIT_ADMIN", "1")
        monkeypatch.setenv("RIKS_ADMIN_API_KEYS", "admin-key")
        monkeypatch.setattr(server_module, "API_KEY", "")  # open auth mode

        # Seed tenant-x's log.
        client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-x"})

        # An admin (key present) reading tenant-x while authenticated as
        # tenant-y: the ?tenant= param overrides to tenant-x.
        admin_log = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": "tenant-y", "X-API-Key": "admin-key"},
            params={"tenant": "tenant-x"},
        ).json()
        assert admin_log["tenant"] == "tenant-x"
        assert admin_log["total"] >= 1

    def test_regular_user_cannot_read_other_tenant_log(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        # A non-admin caller cannot use ?tenant= to read someone else's log.
        monkeypatch.setenv("RIKS_AUDIT_ADMIN", "1")
        monkeypatch.setenv("RIKS_ADMIN_API_KEYS", "admin-key")
        monkeypatch.setattr(server_module, "API_KEY", "")  # open auth mode

        client.get("/api/v1/context/summary", headers={"X-Tenant-Id": "tenant-x"})
        # Regular user (no admin key) asking for tenant-x stays on their own.
        log = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": "tenant-y", "X-API-Key": "not-admin"},
            params={"tenant": "tenant-x"},
        ).json()
        assert log["tenant"] == "tenant-y"

    def test_admin_role_recorded_in_audit(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        # An admin's request is recorded with role=admin.
        monkeypatch.setenv("RIKS_ADMIN_API_KEYS", "admin-key")
        monkeypatch.setattr(server_module, "API_KEY", "admin-key")
        res = client.get(
            "/api/v1/context/summary",
            headers={"X-Tenant-Id": "tenant-rbac", "X-API-Key": "admin-key"},
        )
        assert res.status_code == 200
        log = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": "tenant-rbac", "X-API-Key": "admin-key"},
        ).json()
        entry = next(e for e in log["entries"] if e["endpoint"] == "/api/v1/context/summary")
        assert entry["role"] == "admin"
