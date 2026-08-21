"""E2E HTTP import-path id-preservation test (#180) — CI must pass, no real LLM.

Covers the acceptance criteria for #180 against the in-app TestClient
surface (never a real staging endpoint):

1. The manifest ``id`` field is preserved end-to-end over the HTTP import
   path (episodic/semantic/procedural). Before the fix, the HTTP path
   imported into stores whose ``add()`` generated server-side
   timestamp/uuid ids — the manifest ids were dropped, so ``merge=true``
   dedupe was dead and a re-import duplicated every record.
2. Re-importing the SAME manifest with ``merge=true`` imports 0 records
   and export counts stay constant.
3. ``merge=false`` (wipe + restore) still works, and restores with the
   manifest ids preserved.

The #167 roundtrip suite seeds/asserts in-process and never exercised the
HTTP path where ids were lost; this file closes that gap.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import riks_context_engine.api.server as server_module
from riks_context_engine.api.server import _tenant_memory_registry, app
from riks_context_engine.memory import export as memory_export

TENANT = {"X-Tenant-Id": "id180-tenant", "X-API-Key": "test-api-key"}

EPISODIC_IDS = ("ep_pm1", "ep_pm2", "ep_pm3")
SEMANTIC_IDS = ("sem_pm1", "sem_pm2")
PROCEDURAL_IDS = ("pr_pm1",)


def _manifest() -> dict[str, Any]:
    """A manifest with explicit, stable ids on all three tiers."""
    return {
        "metadata": {
            "schema_version": memory_export.SCHEMA_VERSION,
            "exported_at": "2026-08-21T00:00:00+00:00",
            "tool": "riks-context-engine",
            "export_id": "fixed-id",
        },
        "episodic": [
            {
                "id": EPISODIC_IDS[0],
                "timestamp": "2026-08-20T10:00:00+00:00",
                "content": "deployed the staging image",
                "importance": 0.9,
                "embedding": [0.1, 0.2, 0.3],
                "tags": ["ops"],
                "type": "episodic",
            },
            {
                "id": EPISODIC_IDS[1],
                "timestamp": "2026-08-20T11:00:00+00:00",
                "content": "verified the fail-closed auth behavior",
                "importance": 0.7,
                "embedding": None,
                "tags": ["security"],
                "type": "episodic",
            },
            {
                "id": EPISODIC_IDS[2],
                "timestamp": "2026-08-20T12:00:00+00:00",
                "content": "rotated the API key",
                "importance": 0.5,
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
                "embedding": [0.5, 0.5],
                "type": "semantic",
            },
            {
                "id": SEMANTIC_IDS[1],
                "subject": "user",
                "predicate": "name",
                "object": "Vahit",
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
                "name": "nightly_backup",
                "description": "Nightly memory snapshot routine",
                "steps": ["snapshot", "verify", "archive"],
                "created_at": "2026-08-20T09:00:00+00:00",
                "last_used": "2026-08-20T09:00:00+00:00",
                "use_count": 0,
                "success_rate": 1.0,
                "tags": ["ops"],
                "type": "procedural",
            },
        ],
    }


def _expected_counts() -> dict[str, int]:
    return {"episodic": 3, "semantic": 2, "procedural": 1}


@pytest.fixture(autouse=True)
def _fresh_singleton_stores(tmp_path, monkeypatch):
    """Point the app's singleton memory stores at a per-test temp dir.

    Same pattern as tests/test_api/test_memory_roundtrip_e2e.py: patch the
    lifespan (which creates the singletons the export/import endpoints
    read) and clear the tenant-scoped memory registry so no state leaks.
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
        with TestClient(app, headers=TENANT) as c:
            yield c
    finally:
        server_module.API_KEY = original_key


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _import(client: TestClient, manifest: dict[str, Any], merge: bool) -> dict[str, int]:
    r = client.post(
        "/api/v1/memory/import",
        json={
            "content": json.dumps(manifest),
            "format": "json",
            "merge": merge,
        },
        headers=TENANT,
    )
    assert r.status_code == 200, f"import failed: {r.text}"
    return r.json()["imported"]


def _export_manifest(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/v1/memory/export", params={"format": "json"}, headers=TENANT)
    assert r.status_code == 200, f"export failed: {r.text}"
    body = r.json()
    assert body["counts"] == _expected_counts(), f"unexpected counts: {body['counts']}"
    return json.loads(body["data"])


def _stored_ids(manifest: dict[str, Any], tier: str) -> set[str]:
    return {entry["id"] for entry in manifest[tier]}


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_import_preserves_manifest_ids_and_reimport_imports_zero(client: TestClient) -> None:
    """AC1 + AC2: explicit ids survive the HTTP path; re-import is a no-op."""
    manifest = _manifest()

    imported = _import(client, manifest, merge=True)
    assert imported == _expected_counts(), f"first import wrong: {imported}"

    exported = _export_manifest(client)
    assert _stored_ids(exported, "episodic") == set(EPISODIC_IDS)
    assert _stored_ids(exported, "semantic") == set(SEMANTIC_IDS)
    assert _stored_ids(exported, "procedural") == set(PROCEDURAL_IDS)

    # Same manifest, merge=true again: dedupe by preserved id must skip all.
    reimported = _import(client, manifest, merge=True)
    assert reimported == {"episodic": 0, "semantic": 0, "procedural": 0}, (
        f"re-import must be a no-op, got: {reimported}"
    )

    reexported = _export_manifest(client)
    assert _stored_ids(reexported, "episodic") == set(EPISODIC_IDS)
    assert _stored_ids(reexported, "semantic") == set(SEMANTIC_IDS)
    assert _stored_ids(reexported, "procedural") == set(PROCEDURAL_IDS)


def test_merge_false_wipe_and_restore_preserves_ids(client: TestClient) -> None:
    """AC3: merge=false still wipes + restores, with manifest ids kept."""
    manifest = _manifest()

    first = _import(client, manifest, merge=True)
    assert first == _expected_counts()

    # Wipe + restore the same manifest.
    restored = _import(client, manifest, merge=False)
    assert restored == _expected_counts(), f"restore wrong: {restored}"

    exported = _export_manifest(client)
    assert _stored_ids(exported, "episodic") == set(EPISODIC_IDS)
    assert _stored_ids(exported, "semantic") == set(SEMANTIC_IDS)
    assert _stored_ids(exported, "procedural") == set(PROCEDURAL_IDS)

    # Counts stay constant after another merge=true re-import.
    again = _import(client, manifest, merge=True)
    assert again == {"episodic": 0, "semantic": 0, "procedural": 0}
    _export_manifest(client)  # asserts counts == expected internally


def test_store_generated_ids_when_manifest_id_missing(client: TestClient) -> None:
    """Back-compat: a manifest record WITHOUT an explicit id still imports,
    with a store-generated (timestamp/uuid) id; explicit ids on the other
    records are preserved."""
    manifest = _manifest()
    # Drop the id from the first record of each tier only.
    del manifest["episodic"][0]["id"]
    del manifest["semantic"][0]["id"]
    del manifest["procedural"][0]["id"]

    imported = _import(client, manifest, merge=True)
    assert imported == _expected_counts(), f"import wrong: {imported}"

    exported = _export_manifest(client)
    ep_ids = _stored_ids(exported, "episodic")
    sem_ids = _stored_ids(exported, "semantic")
    pr_ids = _stored_ids(exported, "procedural")
    # Id-less records got server-generated ids; explicit ids survived.
    assert len(ep_ids) == 3 and EPISODIC_IDS[1] in ep_ids and EPISODIC_IDS[2] in ep_ids
    assert len(sem_ids) == 2 and SEMANTIC_IDS[1] in sem_ids
    assert len(pr_ids) == 1
    # Server-generated ids are not the manifest ids.
    generated = (ep_ids - set(EPISODIC_IDS[1:])) | (sem_ids - {SEMANTIC_IDS[1]}) | pr_ids
    assert len(generated) == 3
    assert all(not i.startswith(("ep_pm", "sem_pm", "pr_pm")) for i in generated)
