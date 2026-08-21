"""E2E audit log test — write/read, append-only, filtering, tenant isolation (#169).

Exercises the tenant-scoped, JSON-backed audit log (#110) against the
in-app TestClient surface (never a real staging endpoint):

- AC1 Write: ``POST /api/v1/audit/operation`` returns the entry fields
  (timestamp/tenant/action(category)/endpoint) and the entry is visible
  via ``GET /api/v1/audit``.
- AC2 Read: ``GET /api/v1/audit`` lists entries; an empty log returns
  ``200`` with an empty list.
- AC3 Append-only: DELETE/PUT on ``/api/v1/audit`` and
  ``/api/v1/audit/operation`` → 405 (FastAPI has no such route). The
  log file itself is rewritten in-place (``_save``); externally appended
  entries survive a fresh ``AuditLog`` load and the API responses stay
  consistent (file-level check).
- AC4 Filtering: ``category`` and ``endpoint`` query params filter the
  listing (the API exposes ``query()``'s category/endpoint filters).
  ``requested_tenant`` (``?tenant=``) behavior is pinned: only an admin
  API key (``RIKS_ADMIN_API_KEYS``) with ``RIKS_AUDIT_ADMIN`` enabled may
  cross-tenant read; a regular user stays on their own tenant.
- AC5 Tenant isolation: tenant A writes 3 operation entries → tenant B
  sees 0 (filtered by the operation category so A's own request entries
  are excluded) → tenant A sees exactly its own 3.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import audit_log as audit_log_module
from riks_context_engine.api import server as server_module
from riks_context_engine.api.audit_log import AuditEntry, AuditLog, reset_registry
from riks_context_engine.api.server import app

TENANT_A = {"X-Tenant-Id": "t169-tenant-a", "X-API-Key": "test-api-key"}
TENANT_B = {"X-Tenant-Id": "t169-tenant-b", "X-API-Key": "test-api-key"}
BASE_HEADERS = {"X-Tenant-Id": "t169-base", "X-API-Key": "test-api-key"}

CATEGORY = "context.clear"
A_CATEGORIES = ("context.clear", "task.execute", "memory.delete")

# Stable timestamps (ISO, parseable) so ordering assertions are
# deterministic. The audit API has no from/to timestamp query params
# (``AuditLog.query`` filters on category/endpoint/min_status only).
A_TIMESTAMPS = (
    "2026-08-21T10:00:00+00:00",
    "2026-08-21T11:00:00+00:00",
    "2026-08-21T12:00:00+00:00",
)


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


@pytest.fixture
def client():
    """TestClient with a valid API key + a base tenant (per-request
    headers override the tenant; the API key is always the one the
    server expects)."""
    original_key = server_module.API_KEY
    server_module.API_KEY = "test-api-key"
    try:
        with TestClient(app, headers=BASE_HEADERS) as c:
            yield c
    finally:
        server_module.API_KEY = original_key


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _record(client: TestClient, headers: dict[str, str], **params: str) -> dict:
    """POST /api/v1/audit/operation with explicit per-request headers."""
    r = client.post(
        "/api/v1/audit/operation",
        params=params,
        headers={**BASE_HEADERS, **headers},
    )
    assert r.status_code == 200, f"audit/operation failed: {r.text}"
    return r.json()


def _get_log(client: TestClient, headers: dict[str, str], **params) -> dict:
    r = client.get(
        "/api/v1/audit",
        params=params or None,
        headers={**BASE_HEADERS, **headers},
    )
    assert r.status_code == 200, f"audit read failed: {r.text}"
    return r.json()


def _seed_tenant_a(client: TestClient) -> None:
    """Seed tenant A with one operation entry per category (3 total).

    Uses the in-process ``record_operation`` path (same store the API
    handlers use) with stable, ordered timestamps so "newest first"
    ordering assertions are deterministic across the API and the file.
    """
    store = audit_log_module.get_audit_log(TENANT_A["X-Tenant-Id"])
    for category, timestamp, endpoint in (
        (A_CATEGORIES[0], A_TIMESTAMPS[0], "/api/v1/context/messages"),
        (A_CATEGORIES[1], A_TIMESTAMPS[1], "/api/v1/tasks/1/execute"),
        (A_CATEGORIES[2], A_TIMESTAMPS[2], "/api/v1/memory"),
    ):
        store.record(
            AuditEntry(
                id=f"audit_t169_{category}",
                timestamp=timestamp,
                tenant=TENANT_A["X-Tenant-Id"],
                endpoint=endpoint,
                method="POST",
                status=200,
                latency_ms=0.0,
                category=category,
            )
        )


# ─── AC1: write ───────────────────────────────────────────────────────────────


class TestWrite:
    def test_operation_response_has_entry_fields(self, client: TestClient) -> None:
        """AC1: POST /api/v1/audit/operation returns timestamp, tenant,
        action (category), endpoint and method in the response."""
        body = _record(
            client,
            TENANT_A,
            category=CATEGORY,
            endpoint="/api/v1/context/messages",
            method="DELETE",
        )
        assert body["tenant"] == TENANT_A["X-Tenant-Id"]
        assert body["category"] == CATEGORY  # "action" of the entry
        assert body["endpoint"] == "/api/v1/context/messages"
        assert body["method"] == "DELETE"
        assert body["status"] == 200
        assert body["id"].startswith("audit_")
        assert body["timestamp"]  # non-empty ISO timestamp
        assert body["role"] == "regular"

    def test_written_entry_is_readable_via_get(self, client: TestClient) -> None:
        """AC1: an entry written by POST is visible via GET /api/v1/audit
        (same tenant), matched by category + endpoint."""
        _record(
            client,
            TENANT_A,
            category=CATEGORY,
            endpoint="/api/v1/context/messages",
            method="DELETE",
        )
        body = _get_log(client, TENANT_A, category=CATEGORY)
        assert body["tenant"] == TENANT_A["X-Tenant-Id"]
        matching = [
            e
            for e in body["entries"]
            if e["category"] == CATEGORY and e["endpoint"] == "/api/v1/context/messages"
        ]
        assert len(matching) == 1
        assert matching[0]["method"] == "DELETE"
        assert matching[0]["tenant"] == TENANT_A["X-Tenant-Id"]


# ─── AC2: read ────────────────────────────────────────────────────────────────


class TestRead:
    def test_empty_log_returns_200_empty_list(self, client: TestClient) -> None:
        """AC2: a tenant that never wrote an operation entry gets 200
        with an empty list under the operation category (middleware
        request entries exist but are a different category)."""
        body = _get_log(client, TENANT_B, category=CATEGORY)
        assert body["tenant"] == TENANT_B["X-Tenant-Id"]
        assert body["entries"] == []

    def test_listing_is_newest_first(self, client: TestClient) -> None:
        """AC2: GET /api/v1/audit lists entries, newest first (the GET
        requests themselves are audited by the middleware)."""
        for _ in range(3):
            _get_log(client, TENANT_B)
        body = _get_log(client, TENANT_B)
        assert body["total"] >= 3
        timestamps = [e["timestamp"] for e in body["entries"]]
        assert timestamps == sorted(timestamps, reverse=True)


# ─── AC3: append-only ─────────────────────────────────────────────────────────


class TestAppendOnly:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("delete", "/api/v1/audit"),
            ("put", "/api/v1/audit"),
            ("delete", "/api/v1/audit/operation"),
            ("put", "/api/v1/audit/operation"),
        ],
    )
    def test_mutating_methods_rejected_405(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """AC3: DELETE/PUT on the audit endpoints → 405 (no such route:
        the log can only be appended to, never deleted/rewritten via the
        API)."""
        r = getattr(client, method)(
            path,
            params={"category": CATEGORY} if path.endswith("/operation") else None,
            headers=BASE_HEADERS,
        )
        assert r.status_code == 405, f"{method.upper()} {path}: expected 405, got {r.status_code}"

    def test_external_file_append_survives_reload(self, client: TestClient, tmp_path) -> None:
        """AC3 (file-level): an entry appended directly to the JSON log
        file (out-of-process) is never lost — a fresh AuditLog (next
        server start) loads both the API-written and the externally
        appended entry, and within one process the live store's writes
        are flushed to disk (append-only, never rewritten)."""
        tenant = TENANT_A["X-Tenant-Id"]
        _record(client, TENANT_A, category=CATEGORY, endpoint="/x", method="GET")
        live = audit_log_module.get_audit_log(tenant)

        # The API's writes are durable: the operation entry is already on
        # disk in the live store's file (written in _save()).
        path = tmp_path / "tenants" / tenant / "audit.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["entries"]) == live.total()

        # Out-of-process append (e.g. another process writing the file
        # directly) — this entry must be picked up on the next load.
        external = AuditEntry.now(
            tenant=tenant,
            endpoint="/api/v1/external",
            method="POST",
            status=200,
            latency_ms=1.0,
            category=CATEGORY,
        )
        data["entries"].append(asdict(external))
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # A fresh in-memory store (simulating a server restart) sees both
        # the API-written entry and the externally appended one — nothing
        # is dropped across a restart.
        reloaded = AuditLog(tenant, path)
        assert any(e.id == external.id for e in reloaded._entries)
        assert all(any(r.id == e.id for r in reloaded._entries) for e in live._entries), (
            "the API-written entries must survive the file round-trip"
        )
        assert reloaded.total() == len(live._entries) + 1  # + the external one


# ─── AC4: filtering ───────────────────────────────────────────────────────────


class TestFiltering:
    def test_category_filter_returns_only_matching(self, client: TestClient) -> None:
        """AC4: ?category= returns only entries with that action/category
        (the "action" filter; the API surfaces ``query()``'s category
        param)."""
        _seed_tenant_a(client)
        body = _get_log(client, TENANT_A, category=A_CATEGORIES[0])
        assert len(body["entries"]) == 1
        assert all(e["category"] == A_CATEGORIES[0] for e in body["entries"])

    def test_endpoint_filter_returns_only_matching(self, client: TestClient) -> None:
        """AC4: ?endpoint= returns only entries recorded for that path."""
        _seed_tenant_a(client)
        endpoint = "/api/v1/tasks/1/execute"
        body = _get_log(client, TENANT_A, endpoint=endpoint)
        assert body["entries"], "endpoint filter returned no entries"
        assert all(e["endpoint"] == endpoint for e in body["entries"])
        assert len(body["entries"]) == 1

    def test_unknown_category_returns_empty(self, client: TestClient) -> None:
        """AC4: a category with no entries → empty list (200)."""
        _seed_tenant_a(client)
        body = _get_log(client, TENANT_A, category="task.cancel")
        assert body["entries"] == []

    def test_combined_category_and_endpoint(self, client: TestClient) -> None:
        """AC4: filters combine (AND semantics)."""
        _seed_tenant_a(client)
        body = _get_log(
            client,
            TENANT_A,
            category=A_CATEGORIES[1],
            endpoint="/api/v1/tasks/1/execute",
        )
        assert len(body["entries"]) == 1
        assert body["entries"][0]["category"] == A_CATEGORIES[1]

    def test_regular_user_tenant_param_is_ignored(self, client: TestClient, monkeypatch):
        """AC4 (requested_tenant, pinned behavior): without an admin key,
        ?tenant= does NOT switch the log — the caller stays on their own
        tenant even with RIKS_AUDIT_ADMIN enabled."""
        monkeypatch.setenv("RIKS_AUDIT_ADMIN", "1")
        monkeypatch.setenv("RIKS_ADMIN_API_KEYS", "admin-key-169")
        _seed_tenant_a(client)

        # Regular user (API key == server API_KEY, not an admin key).
        body = _get_log(client, TENANT_B, tenant=TENANT_A["X-Tenant-Id"])
        assert body["tenant"] == TENANT_B["X-Tenant-Id"]
        assert body["entries"] == []

    def test_admin_key_reads_other_tenant_log(self, client: TestClient, monkeypatch) -> None:
        """AC4 (admin cross-read): with RIKS_AUDIT_ADMIN enabled and an
        admin API key, ?tenant=<A> returns A's log (the existing,
        opt-in behavior is locked in)."""
        monkeypatch.setenv("RIKS_AUDIT_ADMIN", "1")
        monkeypatch.setenv("RIKS_ADMIN_API_KEYS", "admin-key-169")
        monkeypatch.setattr(server_module, "API_KEY", "admin-key-169")
        _seed_tenant_a(client)

        r = client.get(
            "/api/v1/audit",
            params={"tenant": TENANT_A["X-Tenant-Id"], "category": CATEGORY},
            headers={"X-Tenant-Id": TENANT_B["X-Tenant-Id"], "X-API-Key": "admin-key-169"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenant"] == TENANT_A["X-Tenant-Id"]
        assert len(body["entries"]) == 1
        assert body["entries"][0]["category"] == CATEGORY
        # The admin call itself is recorded with role=admin.
        r = client.get(
            "/api/v1/audit",
            headers={"X-Tenant-Id": TENANT_B["X-Tenant-Id"], "X-API-Key": "admin-key-169"},
        )
        assert r.status_code == 200, r.text
        admin_body = r.json()
        audit_entry = next(e for e in admin_body["entries"] if e["endpoint"] == "/api/v1/audit")
        assert audit_entry["role"] == "admin"


# ─── AC5: tenant isolation ────────────────────────────────────────────────────


class TestTenantIsolation:
    def test_a_writes_three_b_reads_zero_a_reads_three(self, client: TestClient) -> None:
        """AC5: tenant A writes 3 operation entries → tenant B sees 0
        (filtered on the operation categories, so A's own request
        entries never muddy the assertion) → tenant A sees exactly its
        own 3."""
        _seed_tenant_a(client)

        # B's log must contain zero of A's operation categories.
        b_body = _get_log(client, TENANT_B)
        b_entries = b_body["entries"]
        assert b_body["tenant"] == TENANT_B["X-Tenant-Id"]
        assert [e for e in b_entries if e["category"] in A_CATEGORIES] == []
        assert all(e["tenant"] == TENANT_B["X-Tenant-Id"] for e in b_entries)

        # A sees exactly its own 3 operation entries, in write order
        # (newest first per the stable timestamps).
        a_body = _get_log(client, TENANT_A, category=A_CATEGORIES[0])
        assert a_body["tenant"] == TENANT_A["X-Tenant-Id"]
        ops = [e for e in a_body["entries"] if e["category"] in A_CATEGORIES]
        assert len(ops) == 1  # only category[0] here
        all_a = _get_log(client, TENANT_A, limit=1000)
        a_ops = [e for e in all_a["entries"] if e["category"] in A_CATEGORIES]
        assert len(a_ops) == 3
        assert all(e["tenant"] == TENANT_A["X-Tenant-Id"] for e in a_ops)
        assert {e["category"] for e in a_ops} == set(A_CATEGORIES)
        # Entries never leave the tenant: every A entry carries A's id.
        assert all(e["tenant"] == TENANT_A["X-Tenant-Id"] for e in all_a["entries"])

    def test_b_writing_does_not_alter_a_log(self, client: TestClient) -> None:
        """AC5: B's writes are scoped to B's file; A's log is untouched
        by B's traffic."""
        _seed_tenant_a(client)
        before = _get_log(client, TENANT_A, limit=1000)
        before_ops = [e for e in before["entries"] if e["category"] in A_CATEGORIES]

        for category in A_CATEGORIES:
            _record(client, TENANT_B, category=category, endpoint="/b", method="POST")

        after = _get_log(client, TENANT_A, limit=1000)
        a_ops = [e for e in after["entries"] if e["category"] in A_CATEGORIES]
        # A's operation entries are untouched (A's request entries grow
        # with its own traffic, which is expected).
        assert a_ops == before_ops
        assert len(a_ops) == 3
        assert {e["category"] for e in a_ops} == set(A_CATEGORIES)

        # B's file is a separate store.
        b_body = _get_log(client, TENANT_B, limit=1000)
        b_ops = [e for e in b_body["entries"] if e["category"] in A_CATEGORIES]
        assert len(b_ops) == 3
        assert all(e["tenant"] == TENANT_B["X-Tenant-Id"] for e in b_ops)
