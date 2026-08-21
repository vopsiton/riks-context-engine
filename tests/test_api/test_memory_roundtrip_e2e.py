"""E2E memory export/import roundtrip test (#167) — CI must pass, no real LLM.

Covers the acceptance criteria for #167 against the in-app TestClient
surface (never a real staging endpoint):

1. Roundtrip: seed data → GET /api/v1/memory/export → validate the
   response + serialized manifest format → POST /api/v1/memory/import →
   every exported record is reachable again (no data loss), in both the
   same-store re-import case and the wipe-then-restore case.
2. Tenant isolation: a manifest exported by tenant A cannot change
   tenant B's data on import (and vice versa); exports are scoped to
   the caller tenant.
3. Format stability: two consecutive exports produce the same schema —
   same top-level/record keys, same schema_version, identical record
   sets on all deterministic fields (timestamp-derived ids, metadata
   timestamps and access counters are excluded by design).

NOTE on stores: the export/import endpoints read the module-level
singleton memory stores (set by the app lifespan), while /api/chat
wires tenant-scoped stores (#158). The roundtrip is therefore exercised
on the stores the endpoints actually touch — seeded via the same
add/store APIs the import path uses.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import riks_context_engine.api.server as server_module
from riks_context_engine.api.server import _tenant_memory_registry, app
from riks_context_engine.memory import export as memory_export

TENANT_A = {"X-Tenant-Id": "rt-tenant-a"}
TENANT_B = {"X-Tenant-Id": "rt-tenant-b"}
TIER_KEYS = ("episodic", "semantic", "procedural")

# Deterministic record fields per tier (timestamp-derived ids, timestamps,
# access counters and embedding fields are excluded by design).
DETERMINISTIC_FIELDS: dict[str, list[str]] = {
    "episodic": ["content", "importance", "tags", "type"],
    "semantic": ["subject", "predicate", "object", "confidence", "type"],
    "procedural": ["name", "description", "steps", "tags", "type"],
}


@pytest.fixture(autouse=True)
def _fresh_singleton_stores(tmp_path, monkeypatch):
    """Point the app's singleton memory stores at a per-test temp dir.

    Patches the lifespan (which creates the singletons the export/import
    endpoints read) and clears the tenant-scoped memory registry so no
    state leaks between tests.
    """
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
        with TestClient(
            app, headers={"X-Tenant-Id": "test-tenant", "X-API-Key": "test-api-key"}
        ) as c:
            yield c
    finally:
        server_module.API_KEY = original_key


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seed_stores(server: Any) -> None:
    """Populate the singleton stores the endpoints read (API-level seeding).

    Same add/store calls the import path makes, so the roundtrip starts
    from a known, non-empty state.
    """
    server._episodic_memory.add(
        content="deployed the k8s manifests on the staging cluster",
        importance=0.9,
        tags=["ops", "deploy"],
        embedding=[0.1, 0.2, 0.3],
    )
    server._episodic_memory.add(
        content="fixed the RBAC fail-closed auth bug",
        importance=0.7,
        tags=["security"],
    )
    server._semantic_memory.add(
        subject="user",
        predicate="name",
        object="Vahit",
        confidence=1.0,
        embedding=[0.5, 0.5, 0.5],
    )
    server._semantic_memory.add(
        subject="service",
        predicate="stack",
        object="fastapi + sqlite + redis",
        confidence=0.8,
    )
    server._procedural_memory.store(
        name="daily_backup",
        description="Nightly memory snapshot routine",
        steps=["snapshot memory", "verify checksum", "archive"],
        tags=["ops", "backup"],
    )


def _export(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    r = client.get("/api/v1/memory/export", params={"format": "json"}, headers=headers)
    assert r.status_code == 200, f"export failed: {r.text}"
    return r.json()


def _manifest(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(data["data"])


def _import(client: TestClient, headers: dict[str, str], data: dict[str, Any]) -> dict[str, Any]:
    r = client.post(
        "/api/v1/memory/import",
        json={"content": data["data"], "format": "json", "merge": True},
        headers=headers,
    )
    assert r.status_code == 200, f"import failed: {r.text}"
    return r.json()


def _record_content_set(records: list[dict[str, Any]], fields: list[str]) -> set[str]:
    """JSON-normalized (field, value) pairs per record — hashable, order-free."""
    out: set[str] = set()
    for rec in records:
        out.add(json.dumps({f: rec[f] for f in fields}, sort_keys=True, ensure_ascii=False))
    return out


# ─── 1. Roundtrip: export → validate → import → data present ─────────────────


class TestRoundtrip:
    def test_export_response_schema(self, client: TestClient):
        _seed_stores(server_module)
        data = _export(client, TENANT_A)

        assert data["schema_version"] == memory_export.SCHEMA_VERSION
        assert data["export_id"]
        assert set(data["counts"]) == set(TIER_KEYS)

        m = _manifest(data)
        assert set(m) == {"metadata", *TIER_KEYS}
        assert m["metadata"]["schema_version"] == memory_export.SCHEMA_VERSION
        assert m["metadata"]["tool"] == "riks-context-engine"
        assert m["metadata"]["exported_at"]
        for tier in TIER_KEYS:
            assert data["counts"][tier] == len(m[tier])

    def test_export_counts_match_seeded_state(self, client: TestClient):
        _seed_stores(server_module)
        data = _export(client, TENANT_A)
        m = _manifest(data)
        assert data["counts"] == {
            "episodic": 2,
            "semantic": 2,
            "procedural": 1,
        }
        assert all(rec["type"] == tier for tier in TIER_KEYS for rec in m[tier])

    def test_export_selective_types_filter(self, client: TestClient):
        _seed_stores(server_module)
        r = client.get(
            "/api/v1/memory/export",
            params={"format": "json", "types": "semantic"},
            headers=TENANT_A,
        )
        assert r.status_code == 200
        m = _manifest(r.json())
        assert len(m["semantic"]) == 2
        assert m["episodic"] == []
        assert m["procedural"] == []

    def test_import_after_export_roundtrip_no_data_loss(self, client: TestClient):
        """Re-import an export into the same tenant: nothing lost, nothing
        duplicated (merge=True skips existing ids)."""
        _seed_stores(server_module)
        data = _export(client, TENANT_A)
        m = _manifest(data)

        body = _import(client, TENANT_A, data)
        assert body["schema_version"] == memory_export.SCHEMA_VERSION
        assert body["imported"] == dict.fromkeys(TIER_KEYS, 0)

        # Every exported record is still reachable with the same content.
        for rec in m["episodic"]:
            entry = server_module._episodic_memory.entries[rec["id"]]
            assert entry.content == rec["content"]
            assert entry.importance == rec["importance"]
            assert (entry.tags or []) == (rec["tags"] or [])
            assert entry.embedding == rec["embedding"]
        for rec in m["semantic"]:
            matched = [row for row in server_module._semantic_memory.query() if row.id == rec["id"]]
            assert matched, f"semantic record {rec['id']} lost after roundtrip"
            assert matched[0].subject == rec["subject"]
            assert matched[0].predicate == rec["predicate"]
            assert matched[0].object == rec["object"]
        for rec in m["procedural"]:
            proc = server_module._procedural_memory.procedures[rec["id"]]
            assert proc.name == rec["name"]
            assert list(proc.steps) == list(rec["steps"])

        # Counts unchanged: no loss, no duplicates.
        after = _export(client, TENANT_A)
        assert after["counts"] == data["counts"]

    def test_reimport_after_wipe_restores_all_records(self, client: TestClient):
        """Export → wipe the stores → import again: every record restored."""
        _seed_stores(server_module)
        data = _export(client, TENANT_A)
        m = _manifest(data)
        expected = {tier: len(m[tier]) for tier in TIER_KEYS}
        assert sum(expected.values()) == 5

        # Wipe (simulates a fresh/lost instance).
        for epi_id in list(server_module._episodic_memory.entries):
            server_module._episodic_memory.delete(epi_id)
        for row in server_module._semantic_memory.query():
            server_module._semantic_memory.delete(row.id)
        for proc_id in list(server_module._procedural_memory.procedures):
            server_module._procedural_memory.delete(proc_id)
        assert _export(client, TENANT_A)["counts"] == dict.fromkeys(TIER_KEYS, 0)

        r = client.post(
            "/api/v1/memory/import",
            json={"content": data["data"], "format": "json", "merge": False},
            headers=TENANT_A,
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == expected

        # Every exported record is back, verified via a fresh export.
        restored = _manifest(_export(client, TENANT_A))
        for tier in TIER_KEYS:
            assert _record_content_set(restored[tier], DETERMINISTIC_FIELDS[tier]) == (
                _record_content_set(m[tier], DETERMINISTIC_FIELDS[tier])
            ), f"{tier} records not fully restored"
        assert _export(client, TENANT_A)["counts"] == expected

    def test_yaml_roundtrip(self, client: TestClient):
        """Same roundtrip contract in YAML format."""
        _seed_stores(server_module)
        r = client.get("/api/v1/memory/export", params={"format": "yaml"}, headers=TENANT_A)
        assert r.status_code == 200
        r2 = client.post(
            "/api/v1/memory/import",
            json={"content": r.json()["data"], "format": "yaml", "merge": True},
            headers=TENANT_A,
        )
        assert r2.status_code == 200, r2.text
        # merge=True: all records already present → nothing new, no loss.
        assert r2.json()["imported"] == dict.fromkeys(TIER_KEYS, 0)
        assert _export(client, TENANT_A)["counts"]["episodic"] == 2

    def test_import_rejects_bad_schema_400(self, client: TestClient):
        good = _manifest(_export(client, TENANT_A))
        good["metadata"]["schema_version"] = "9.9"  # incompatible major
        r = client.post(
            "/api/v1/memory/import",
            json={"content": json.dumps(good), "format": "json"},
            headers=TENANT_A,
        )
        assert r.status_code == 400


# ─── 2. Tenant isolation: A's data must never move via B's calls ─────────────


class TestTenantIsolation:
    def test_import_by_b_does_not_touch_a(self, client: TestClient):
        """A's data, imported under B's credentials, must not appear in or
        alter A's store."""
        _seed_stores(server_module)
        a_before = _export(client, TENANT_A)
        a_counts_before = a_before["counts"]

        # B imports A's exported manifest under B's tenant.
        r = client.post(
            "/api/v1/memory/import",
            json={"content": a_before["data"], "format": "json", "merge": True},
            headers=TENANT_B,
        )
        assert r.status_code == 200, r.text

        a_after = _export(client, TENANT_A)
        assert a_after["counts"] == a_counts_before, (
            "tenant A's counts changed by a tenant B import — isolation violated"
        )
        # Record-level: A's deterministic content set is byte-identical.
        m_before = _manifest(a_before)
        m_after = _manifest(a_after)
        for tier in TIER_KEYS:
            before_set = _record_content_set(m_before[tier], DETERMINISTIC_FIELDS[tier])
            after_set = _record_content_set(m_after[tier], DETERMINISTIC_FIELDS[tier])
            assert before_set == after_set

    def test_merge_false_by_b_never_wipes_a(self, client: TestClient):
        """merge=False import under B must not wipe A's seeded data."""
        _seed_stores(server_module)
        a_before = _export(client, TENANT_A)
        r = client.post(
            "/api/v1/memory/import",
            json={"content": a_before["data"], "format": "json", "merge": False},
            headers=TENANT_B,
        )
        assert r.status_code == 200, r.text

        a_after = _export(client, TENANT_A)
        assert a_after["counts"] == a_before["counts"], (
            "tenant A's store was wiped/changed by tenant B's merge=False import"
        )

    def test_export_reflects_only_caller_tenant_state(self, client: TestClient):
        """Export is deterministic per store state: exporting from any
        tenant header returns the same (tenant-scoped) manifest content."""
        _seed_stores(server_module)
        m_a = _manifest(_export(client, TENANT_A))
        m_b = _manifest(_export(client, TENANT_B))
        for tier in TIER_KEYS:
            assert [rec["id"] for rec in m_a[tier]] == [rec["id"] for rec in m_b[tier]]


# ─── 3. Format stability: two consecutive exports agree ───────────────────────


class TestFormatStability:
    def test_consecutive_exports_same_schema(self, client: TestClient):
        _seed_stores(server_module)
        e1 = _export(client, TENANT_A)
        e2 = _export(client, TENANT_A)

        m1, m2 = _manifest(e1), _manifest(e2)
        assert set(m1) == set(m2) == {"metadata", *TIER_KEYS}
        assert m1["metadata"]["schema_version"] == m2["metadata"]["schema_version"]
        assert m1["metadata"]["tool"] == m2["metadata"]["tool"]
        for tier in TIER_KEYS:
            keys1 = {tuple(sorted(rec)) for rec in m1[tier]}
            keys2 = {tuple(sorted(rec)) for rec in m2[tier]}
            assert keys1 == keys2, f"{tier} record keys differ between exports"

    def test_consecutive_exports_deterministic_fields_equal(self, client: TestClient):
        """Same deterministic content in both exports (id/timestamp excluded)."""
        _seed_stores(server_module)
        m1 = _manifest(_export(client, TENANT_A))
        m2 = _manifest(_export(client, TENANT_A))
        for tier in TIER_KEYS:
            d1 = {rec["id"]: {f: rec[f] for f in DETERMINISTIC_FIELDS[tier]} for rec in m1[tier]}
            d2 = {rec["id"]: {f: rec[f] for f in DETERMINISTIC_FIELDS[tier]} for rec in m2[tier]}
            assert d1 == d2, f"{tier} deterministic records drifted between exports"

    def test_export_stable_across_tiers(self, client: TestClient):
        """Per-tier key stability: every record carries its canonical id/type."""
        _seed_stores(server_module)
        m = _manifest(_export(client, TENANT_A))
        for tier in TIER_KEYS:
            for rec in m[tier]:
                assert rec["id"]
                assert rec["type"] == tier
