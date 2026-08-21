"""E2E tenant-scoping test for memory import/export (#184) — P1, CI must pass.

Closes the isolation hole found in staging (#183): before the fix,
``POST /api/v1/memory/import`` and ``GET /api/v1/memory/export`` (plus the
``GET /`` alias) read/wrote the module-level **singleton** memory stores
instead of the caller's tenant-scoped stores, so tenant A's import was
visible in tenant B's export.

After the fix both endpoints (and the alias) resolve the caller's stores
from the ``TenantMemoryRegistry`` — the same pattern /api/chat uses (#158):
each tenant gets its own EpisodicMemory/SemanticMemory/ProceduralMemory
backed by tenant-scoped file paths.

Covers the acceptance criteria against the in-app TestClient surface
(never a real staging endpoint):

- AC2: tenant A import (3 episodic) → tenant B export → 0 (isolation).
- AC3: tenant A import → tenant A export → the same 3 records (roundtrip).
- Import idempotency: merge=true re-import imports 0 (no duplicates).
- Semantic + procedural tiers are tenant-scoped too (≥1 test per tier).
- Request without a tenant header on a protected endpoint → 401
  (fail-closed, #166 behavior must stay intact).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import riks_context_engine.api.server as server_module
from riks_context_engine.api.server import _tenant_memory_registry, app
from riks_context_engine.memory import export as memory_export

TENANT_A = {"X-Tenant-Id": "t184-tenant-a", "X-API-Key": "test-api-key"}
TENANT_B = {"X-Tenant-Id": "t184-tenant-b", "X-API-Key": "test-api-key"}
API_KEY_ONLY = {"X-API-Key": "test-api-key"}  # no X-Tenant-Id
BASE_HEADERS = {"X-Tenant-Id": "test-tenant"}  # client default (base) tenant

EPISODIC_IDS = ("t184_ep1", "t184_ep2", "t184_ep3")
SEMANTIC_IDS = ("t184_sem1", "t184_sem2")
PROCEDURAL_IDS = ("t184_proc1",)


def _manifest() -> dict[str, Any]:
    """Manifest with stable explicit ids across all three tiers."""
    return {
        "metadata": {
            "schema_version": memory_export.SCHEMA_VERSION,
            "exported_at": "2026-08-21T00:00:00+00:00",
            "tool": "riks-context-engine",
            "export_id": "t184-fixed",
        },
        "episodic": [
            {
                "id": EPISODIC_IDS[0],
                "timestamp": "2026-08-20T10:00:00+00:00",
                "content": "shipped the staging tenant-scoping fix",
                "importance": 0.9,
                "embedding": None,
                "tags": ["ops"],
                "type": "episodic",
            },
            {
                "id": EPISODIC_IDS[1],
                "timestamp": "2026-08-20T11:00:00+00:00",
                "content": "verified cross-tenant export isolation",
                "importance": 0.8,
                "embedding": None,
                "tags": ["security"],
                "type": "episodic",
            },
            {
                "id": EPISODIC_IDS[2],
                "timestamp": "2026-08-20T12:00:00+00:00",
                "content": "rotated the import pipeline credentials",
                "importance": 0.6,
                "embedding": None,
                "tags": ["security", "ops"],
                "type": "episodic",
            },
        ],
        "semantic": [
            {
                "id": SEMANTIC_IDS[0],
                "subject": "service",
                "predicate": "stack",
                "object": "fastapi + sqlite",
                "confidence": 0.9,
                "created_at": "2026-08-20T10:00:00+00:00",
                "last_accessed": "2026-08-20T10:00:00+00:00",
                "access_count": 0,
                "embedding": None,
                "type": "semantic",
            },
            {
                "id": SEMANTIC_IDS[1],
                "subject": "user",
                "predicate": "role",
                "object": "opsiton-lead",
                "confidence": 1.0,
                "created_at": "2026-08-20T11:00:00+00:00",
                "last_accessed": "2026-08-20T11:00:00+00:00",
                "access_count": 0,
                "embedding": None,
                "type": "semantic",
            },
        ],
        "procedural": [
            {
                "id": PROCEDURAL_IDS[0],
                "name": "tenant_scoping_check",
                "description": "Verify import/export isolation per tenant",
                "steps": ["import as A", "export as B", "assert zero"],
                "created_at": "2026-08-20T09:00:00+00:00",
                "last_used": "2026-08-20T09:00:00+00:00",
                "use_count": 0,
                "success_rate": 1.0,
                "tags": ["security"],
                "type": "procedural",
            },
        ],
    }


def _expected_counts() -> dict[str, int]:
    return {"episodic": 3, "semantic": 2, "procedural": 1}


@pytest.fixture(autouse=True)
def _fresh_tenant_stores(tmp_path, monkeypatch):
    """Isolate the tenant-scoped registry in a per-test temp dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _tenant_memory_registry._semantic.clear()
    _tenant_memory_registry._episodic.clear()
    _tenant_memory_registry._procedural.clear()
    _tenant_memory_registry._data_dir = str(tmp_path)

    async def _fresh_lifespan(_app: Any):
        yield

    monkeypatch.setattr(server_module, "lifespan", _fresh_lifespan)
    yield
    _tenant_memory_registry._semantic.clear()
    _tenant_memory_registry._episodic.clear()
    _tenant_memory_registry._procedural.clear()


@pytest.fixture
def client():
    original_key = server_module.API_KEY
    server_module.API_KEY = "test-api-key"
    try:
        with TestClient(app, headers=TENANT_A) as c:
            yield c
    finally:
        server_module.API_KEY = original_key


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _import(
    client: TestClient, headers: dict[str, str], manifest: dict[str, Any]
) -> dict[str, Any]:
    # Explicit headers replace the client defaults; always merge BASE_HEADERS.
    r = client.post(
        "/api/v1/memory/import",
        json={"content": json.dumps(manifest), "format": "json", "merge": True},
        headers={**BASE_HEADERS, **headers},
    )
    assert r.status_code == 200, f"import failed: {r.text}"
    return r.json()


def _export_body(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    """Tenant-scoped export. Explicit headers REPLACE the client defaults
    (TestClient does not merge request headers with the client's base
    headers), so the base tenant is always passed explicitly."""
    r = client.get(
        "/api/v1/memory/export",
        params={"format": "json"},
        headers={**BASE_HEADERS, **headers},
    )
    assert r.status_code == 200, f"export failed: {r.text}"
    return r.json()


def _export_ids(body: dict[str, Any], tier: str) -> set[str]:
    return {rec["id"] for rec in json.loads(body["data"])[tier]}


# ─── AC2: cross-tenant isolation ──────────────────────────────────────────────


class TestCrossTenantIsolation:
    def test_a_import_then_b_export_is_empty(self, client: TestClient) -> None:
        """AC2: tenant A imports 3 episodic → tenant B export sees 0."""
        body = _import(client, TENANT_A, _manifest())
        assert body["imported"] == _expected_counts()

        b_export = _export_body(client, TENANT_B)
        assert b_export["counts"] == {"episodic": 0, "semantic": 0, "procedural": 0}
        m = json.loads(b_export["data"])
        assert m["episodic"] == [] and m["semantic"] == [] and m["procedural"] == []

        # A still sees its own 3 episodic records.
        a_export = _export_body(client, TENANT_A)
        assert a_export["counts"] == _expected_counts()
        assert _export_ids(a_export, "episodic") == set(EPISODIC_IDS)

    def test_a_export_then_b_import_leaves_a_untouched(self, client: TestClient) -> None:
        """A's exported manifest, imported by B, must not alter A's store."""
        _import(client, TENANT_A, _manifest())
        a_export = _export_body(client, TENANT_A)
        assert a_export["counts"] == _expected_counts()
        client.post(
            "/api/v1/memory/import",
            json={"content": a_export["data"], "format": "json", "merge": True},
            headers={**BASE_HEADERS, **TENANT_B},
        )

        a_after = _export_body(client, TENANT_A)
        assert a_after["counts"] == _expected_counts()
        assert _export_ids(a_after, "episodic") == set(EPISODIC_IDS)

    def test_semantic_tier_isolated(self, client: TestClient) -> None:
        """Semantic tier is tenant-scoped: B sees 0, A sees its own 2."""
        _import(client, TENANT_A, _manifest())

        b_body = _export_body(client, TENANT_B)
        assert json.loads(b_body["data"])["semantic"] == []
        assert b_body["counts"]["semantic"] == 0
        assert _export_ids(_export_body(client, TENANT_A), "semantic") == set(SEMANTIC_IDS)

    def test_procedural_tier_isolated(self, client: TestClient) -> None:
        """Procedural tier is tenant-scoped: B sees 0, A sees its own 1."""
        _import(client, TENANT_A, _manifest())

        b_body = _export_body(client, TENANT_B)
        assert json.loads(b_body["data"])["procedural"] == []
        assert b_body["counts"]["procedural"] == 0
        assert _export_ids(_export_body(client, TENANT_A), "procedural") == set(PROCEDURAL_IDS)


# ─── AC3: same-tenant roundtrip ───────────────────────────────────────────────


class TestSameTenantRoundtrip:
    def test_a_import_then_a_export_roundtrip(self, client: TestClient) -> None:
        """AC3: A imports 3 episodic → A export returns the same 3."""
        _import(client, TENANT_A, _manifest())

        body = _export_body(client, TENANT_A)
        assert body["counts"] == _expected_counts()
        m = json.loads(body["data"])
        assert _export_ids(body, "episodic") == set(EPISODIC_IDS)
        # Content-level roundtrip: the imported content is intact.
        by_id = {rec["id"]: rec for rec in m["episodic"]}
        assert by_id[EPISODIC_IDS[0]]["content"] == "shipped the staging tenant-scoping fix"
        assert by_id[EPISODIC_IDS[1]]["importance"] == 0.8
        assert by_id[EPISODIC_IDS[2]]["tags"] == ["security", "ops"]
        assert _export_ids(body, "semantic") == set(SEMANTIC_IDS)
        assert _export_ids(body, "procedural") == set(PROCEDURAL_IDS)


# ─── Import idempotency ───────────────────────────────────────────────────────


class TestImportIdempotency:
    def test_merge_true_reimport_imports_zero(self, client: TestClient) -> None:
        """merge=true: a second import of the same manifest is a no-op
        (duplicate ids are skipped), counts stay constant."""
        manifest = _manifest()
        first = _import(client, TENANT_A, manifest)
        assert first["imported"] == _expected_counts()

        second = _import(client, TENANT_A, manifest)
        assert second["imported"] == {"episodic": 0, "semantic": 0, "procedural": 0}, (
            f"re-import must not duplicate, got: {second['imported']}"
        )

        body = _export_body(client, TENANT_A)
        assert body["counts"] == _expected_counts()
        assert len(json.loads(body["data"])["episodic"]) == 3

    def test_reimport_under_different_tenant_is_scoped(self, client: TestClient) -> None:
        """Re-importing under tenant B writes only to B's store."""
        manifest = _manifest()
        _import(client, TENANT_A, manifest)
        b_first = _import(client, TENANT_B, manifest)
        assert b_first["imported"] == _expected_counts()
        # A is untouched; B has its own copy.
        assert _export_body(client, TENANT_A)["counts"] == _expected_counts()
        assert _export_body(client, TENANT_B)["counts"] == _expected_counts()


# ─── Fail-closed auth (must not regress #166) ─────────────────────────────────


class TestFailClosed:
    # NOTE: the shared ``client`` fixture is created with base headers
    # (X-Tenant-Id: test-tenant). httpx does NOT let per-request headers
    # *remove* a client-level header — it re-sends the default tenant on
    # every request. So a genuinely tenant-less request needs a fresh
    # TestClient without base headers (that is what the real network does).

    def test_missing_tenant_header_export_401(self, client: TestClient) -> None:
        with TestClient(app) as fresh:
            r = fresh.get(
                "/api/v1/memory/export",
                params={"format": "json"},
                headers={"X-API-Key": "test-api-key"},
            )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_missing_tenant_header_import_401(self, client: TestClient) -> None:
        with TestClient(app) as fresh:
            r = fresh.post(
                "/api/v1/memory/import",
                json={"content": json.dumps(_manifest()), "format": "json"},
                headers={"X-API-Key": "test-api-key"},
            )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_empty_tenant_header_401(self, client: TestClient) -> None:
        r = client.get(
            "/api/v1/memory/export",
            params={"format": "json"},
            headers={"X-Tenant-Id": "   ", "X-API-Key": "test-api-key"},
        )
        assert r.status_code == 401

    def test_root_alias_no_tenant_serves_ui_not_export(
        self, client: TestClient, monkeypatch
    ) -> None:
        """GET / is a protected path: a tenant-less request (fresh client)
        gets 401 from the API-key middleware; a request with a tenant
        serves the UI file when deployed — never the (scoped) export
        branch for unauthenticated callers."""
        import os

        # Tenant-less request is rejected outright (fail-closed, #166).
        with TestClient(app) as fresh:
            r = fresh.get("/", headers={"X-API-Key": "test-api-key"})
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
        # With a tenant: if the UI is deployed, GET / serves the UI file,
        # not the export branch (no leak surface for the unauthenticated
        # UI-load path).
        monkeypatch.setenv("UI_PATH", os.path.join(os.getcwd(), "ui", "index.html"))
        # Only reachable when the UI file exists (CI checks out the repo).
        if not os.path.exists(os.environ["UI_PATH"]):
            pytest.skip("ui/index.html not present in this environment")
        r = client.get("/", headers=API_KEY_ONLY)
        assert r.status_code == 200, r.text
        assert "export_id" not in r.text

    def test_root_alias_export_is_tenant_scoped(self, client: TestClient, monkeypatch) -> None:
        """With a tenant header and no UI deployed, GET / exports the
        caller's scoped memory (the legacy alias must not leak another
        tenant's data either)."""
        # Point the UI path at a missing file so the alias takes the export
        # branch; seed a tenant's store first.
        monkeypatch.setenv("UI_PATH", "/nonexistent/ui/index.html")
        _import(client, TENANT_A, _manifest())

        r_b = client.get("/", headers={**BASE_HEADERS, **TENANT_B})
        assert r_b.status_code == 200, r_b.text
        body_b = r_b.json()
        assert body_b["counts"] == {"episodic": 0, "semantic": 0, "procedural": 0}, (
            "GET / alias leaked data for tenant B — not tenant-scoped"
        )

        r_a = client.get("/", headers={**BASE_HEADERS, **TENANT_A})
        assert r_a.status_code == 200, r_a.text
        body_a = r_a.json()
        assert body_a["counts"]["episodic"] == 3


# ─── Audit hook: import is recorded under the caller's tenant ─────────────────


def test_import_audit_uses_request_tenant(client: TestClient) -> None:
    """The critical-operation audit entry (#110) is recorded under the
    caller's tenant from request.state, not the RIKS_TENANT_ID env fallback."""
    _import(client, TENANT_A, _manifest())

    r = client.get(
        "/api/v1/audit",
        params={"category": "memory.import"},
        headers=TENANT_A,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant"] == "t184-tenant-a"
    matching = [e for e in body["entries"] if e["endpoint"] == "/api/v1/memory/import"]
    assert matching, "memory.import audit entry missing for the caller's tenant"
    assert all(e["tenant"] == "t184-tenant-a" for e in matching)
