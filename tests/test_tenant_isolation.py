"""Tests for multi-tenant isolation (#102).

Covers:
1. Tenant ID header validation — missing/empty/malformed -> 401 (consistent)
2. Context query isolation — tenant A cannot read tenant B's context
3. Regression: existing endpoints still work with a valid tenant header
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api.server import app
from riks_context_engine.multi_tenant import (
    TENANT_HEADER,
    TenantContextRegistry,
    TenantValidationError,
    assert_same_tenant,
    validate_tenant_id,
)

VALID_TENANT = "tenant-a"
VALID_TENANT_B = "tenant-b"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _headers(tenant: str | None = VALID_TENANT) -> dict[str, str]:
    if tenant is None:
        return {}
    return {TENANT_HEADER: tenant}


# ─── 1. Header validation (criterion 1) ──────────────────────────────────────


class TestTenantHeaderValidation:
    """Missing or malformed X-Tenant-Id must be rejected with 401."""

    def test_missing_header_rejected_401(self, client: TestClient) -> None:
        resp = client.get("/api/v1/context/summary")
        assert resp.status_code == 401
        assert "X-Tenant-Id" in resp.json()["detail"]

    def test_empty_header_rejected_401(self, client: TestClient) -> None:
        resp = client.get("/api/v1/context/summary", headers=_headers(""))
        assert resp.status_code == 401

    def test_whitespace_header_rejected_401(self, client: TestClient) -> None:
        resp = client.get("/api/v1/context/summary", headers=_headers("   "))
        assert resp.status_code == 401

    def test_malformed_header_rejected_401(self, client: TestClient) -> None:
        # Path separator / header-injection attempt
        resp = client.get("/api/v1/context/summary", headers=_headers("tenant/../etc"))
        assert resp.status_code == 401

    def test_overlong_header_rejected_401(self, client: TestClient) -> None:
        resp = client.get("/api/v1/context/summary", headers=_headers("a" * 65))
        assert resp.status_code == 401

    def test_valid_header_accepted_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/context/summary", headers=_headers())
        assert resp.status_code == 200
        assert "current_tokens" in resp.json()

    def test_health_unprotected_no_tenant_needed(self, client: TestClient) -> None:
        # /health is outside the protected set -> works without tenant header
        resp = client.get("/health")
        assert resp.status_code == 200


class TestValidateTenantIdUnit:
    def test_valid(self) -> None:
        assert validate_tenant_id("tenant-1.x") == "tenant-1.x"

    def test_strips_whitespace(self) -> None:
        assert validate_tenant_id("  tenant-1  ") == "tenant-1"

    @pytest.mark.parametrize(
        "raw",
        [None, "", "   ", "a" * 65, "tenant/../x", "tenant name", "t\nx", "é"],
    )
    def test_invalid_raises(self, raw: object) -> None:
        with pytest.raises(TenantValidationError):
            validate_tenant_id(raw)  # type: ignore[arg-type]


class TestAssertSameTenantUnit:
    def test_same_ok(self) -> None:
        assert_same_tenant("t1", "t1")

    @pytest.mark.parametrize("req", [None, "t2", ""])
    def test_foreign_raises(self, req: str | None) -> None:
        with pytest.raises(TenantValidationError):
            assert_same_tenant(req, "t1")


# ─── 2. Context isolation (criterion 2) ──────────────────────────────────────


class TestContextIsolation:
    """Tenant A's context must be invisible to tenant B."""

    def test_tenant_b_cannot_see_tenant_a_messages(self, client: TestClient) -> None:
        # Tenant A writes 3 messages
        for i in range(3):
            resp = client.post(
                "/api/v1/context/messages",
                json={"role": "user", "content": f"A-secret-{i}"},
                headers=_headers(VALID_TENANT),
            )
            assert resp.status_code == 200, resp.text

        # Tenant A sees its own 3 messages
        resp_a = client.get("/api/v1/context/messages", headers=_headers(VALID_TENANT))
        assert resp_a.status_code == 200
        assert len(resp_a.json()) == 3

        # Tenant B sees ZERO messages (isolation), not tenant A's
        resp_b = client.get("/api/v1/context/messages", headers=_headers(VALID_TENANT_B))
        assert resp_b.status_code == 200
        assert resp_b.json() == []

    def test_tenant_summary_isolated(self, client: TestClient) -> None:
        client.post(
            "/api/v1/context/messages",
            json={"role": "assistant", "content": "isolated-payload"},
            headers=_headers(VALID_TENANT),
        )
        summary_a = client.get("/api/v1/context/summary", headers=_headers(VALID_TENANT)).json()
        summary_b = client.get("/api/v1/context/summary", headers=_headers(VALID_TENANT_B)).json()
        assert summary_a["messages_count"] > 0
        assert summary_b["messages_count"] == 0

    def test_registry_structural_isolation(self) -> None:
        reg = TenantContextRegistry(max_tokens=1000)
        mgr_a = reg.get("alpha")
        mgr_b = reg.get("beta")
        mgr_a.add(role="user", content="alpha-only")
        assert len(mgr_b.get_messages(include_pruned=False)) == 0
        # Same manager instance per tenant, distinct across tenants
        assert reg.get("alpha") is mgr_a
        assert reg.get("beta") is mgr_b
        assert mgr_a is not mgr_b


# ─── 3. MCP tool isolation (tenant_id param) ─────────────────────────────────


class TestMcpTenantIsolation:
    def test_mcp_context_summary_isolated(self) -> None:
        from riks_context_engine.mcp.handlers import ToolHandler

        handler = ToolHandler(data_dir="/tmp/ora-test-mcp")
        r_a = handler.context_add_message(
            {"tenant_id": "mcp-a", "role": "user", "content": "mcp-a-data"}
        )
        assert r_a["status"] == "added"

        summary_a = handler.context_get_summary({"tenant_id": "mcp-a"})
        summary_b = handler.context_get_summary({"tenant_id": "mcp-b"})
        assert summary_a["messages_count"] >= 1
        assert summary_b["messages_count"] == 0

    def test_mcp_missing_tenant_rejected(self) -> None:
        from riks_context_engine.mcp.handlers import TenantIsolationError, ToolHandler

        handler = ToolHandler(data_dir="/tmp/ora-test-mcp2")
        with pytest.raises(TenantIsolationError):
            handler.context_add_message({"role": "user", "content": "no-tenant"})

    def test_mcp_malformed_tenant_rejected(self) -> None:
        from riks_context_engine.mcp.handlers import TenantIsolationError, ToolHandler

        handler = ToolHandler(data_dir="/tmp/ora-test-mcp3")
        with pytest.raises(TenantIsolationError):
            handler.context_get_summary({"tenant_id": "bad tenant!!"})


# ─── 4. Regression: existing endpoints with a valid tenant header ────────────


class TestRegression:
    def test_chat_requires_no_tenant_still_works(self, client: TestClient) -> None:
        # /api/chat is protected (API key) but we only test that tenant
        # middleware doesn't break the request path when header is present.
        resp = client.post(
            "/api/chat",
            json={"message": "hi"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert "hi" in resp.json()["response"]
