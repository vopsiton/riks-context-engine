"""E2E 'does it remember?' test (#158) — CI must pass, no real LLM required.

Flow (tenant-scoped):
1. POST /api/chat "Benim adım Vahit" (tenant A)
2. POST /api/chat "Adım ne?" (tenant A) → response MUST contain "Vahit"
3. POST /api/chat "Adım ne?" (tenant B) → response MUST NOT contain "Vahit"
   (tenant isolation)

The deterministic mock LLM stub (in chat_context._stub_llm) reads the
context block and answers name questions from it — proving the wiring:
message → context window → prompt → LLM call → reply.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api.server import app, _tenant_registry, _tenant_memory_registry


@pytest.fixture(autouse=True)
def _reset_tenants(tmp_path):
    """Fresh tenant registries per test (no cross-test leakage)."""
    from riks_context_engine.multi_tenant import TenantContextRegistry, TenantMemoryRegistry

    _tenant_registry._managers.clear()
    _tenant_memory_registry._semantic.clear()
    _tenant_memory_registry._data_dir = str(tmp_path)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


TENANT_A = {"X-Tenant-Id": "e2e-tenant-a"}
TENANT_B = {"X-Tenant-Id": "e2e-tenant-b"}


def _chat(client: TestClient, headers: dict, message: str) -> str:
    r = client.post("/api/chat", json={"message": message, "model": "gemma4:31b"}, headers=headers)
    assert r.status_code == 200, f"unexpected status {r.status_code}: {r.text}"
    return r.json()["response"]


class TestChatMemoryE2E:
    """'Gerçekten hafıza tutuyor mu?' — deterministik, CI'da geçer."""

    def test_remember_name_same_tenant(self, client):
        """(1) 'Benim adım Vahit' → (2) 'Adım ne?' → cevap 'Vahit' içerir."""
        _chat(client, TENANT_A, "Benim adım Vahit")
        reply = _chat(client, TENANT_A, "Adım ne?")
        assert "Vahit" in reply, f"Memory not retained: {reply!r}"

    def test_tenant_isolation_negative(self, client):
        """Negatif: farklı tenant 'Adım ne?' → cevapta 'Vahit' OLMAMALI."""
        _chat(client, TENANT_A, "Benim adım Vahit")
        reply_b = _chat(client, TENANT_B, "Adım ne?")
        assert "Vahit" not in reply_b, f"Tenant isolation violated: {reply_b!r}"

    def test_context_window_written(self, client):
        """(a) Write: exchange appears in the tenant context window."""
        _chat(client, TENANT_A, "Benim adım Vahit")
        r = client.get("/api/v1/context/messages", headers=TENANT_A)
        assert r.status_code == 200
        msgs = r.json()
        contents = " ".join(m["content"] for m in msgs)
        assert "Benim adım Vahit" in contents

    def test_semantic_memory_written(self, client):
        """(a) Write: name fact extracted into tenant semantic memory."""
        _chat(client, TENANT_A, "Benim adım Vahit")
        sem = _tenant_memory_registry.get_semantic("e2e-tenant-a")
        entries = sem.query(subject="user", predicate="name")
        assert len(entries) == 1
        assert entries[0].object == "Vahit"

    def test_context_block_injected_into_prompt(self, client):
        """(b) Read: the context block is built from the context window."""
        from riks_context_engine.chat_context import build_context_block

        _chat(client, TENANT_A, "Benim adım Vahit")
        ctx = _tenant_registry.get("e2e-tenant-a")
        sem = _tenant_memory_registry.get_semantic("e2e-tenant-a")
        block = build_context_block(ctx, sem, "Adım ne?")
        assert "Vahit" in block
        assert "Recent conversation" in block or "Relevant facts" in block

    def test_english_name_pattern(self, client):
        """English self-intro also works ('My name is Vahit')."""
        _chat(client, TENANT_A, "My name is Vahit")
        reply = _chat(client, TENANT_A, "What is my name?")
        assert "Vahit" in reply, f"English name not retained: {reply!r}"
