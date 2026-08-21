"""E2E context window manager tests (#168) — CI must pass, no real LLM.

Covers the acceptance criteria for #168 against the in-app TestClient
surface (never a real staging endpoint):

1. **Last-N behavior**: N+ messages in a tenant context window → only the
   most recent N flow into ``build_context_block`` (older ones excluded).
2. **Token-budget truncation**: over budget, OLDER messages are dropped
   from the block and the NEWEST are kept — no error is raised.
3. **Tenant isolation**: tenant A's context never appears in tenant B's
   (GET /api/v1/context/messages and /api/chat), and clearing/wiping B's
   store never touches A's.
4. **/api/chat tenant-scoped wiring (#158)**: a chat exchange under tenant
   A lands in A's tenant-scoped ContextWindowManager only; B's /api/chat
   response cannot see A's context.
5. **ECHO MODE red/green (#165 regression)**: unconditional — no
   skip/xfail. If /api/chat still answers with the old ECHO MODE stub
   ("Context engine entegrasyonu yakında aktif olacak.") instead of a
   context-aware, model-tagged reply, this test FAILS. On CI (TestClient,
   current code) it is green; on the OLD staging image (pre-#165 wiring)
   it is red — that is the point (staging deploy happens after this PR).

Consistent with the existing tests/test_api/ fixture patterns
(test_memory_roundtrip_e2e.py, test_memory_import_id_preservation_e2e.py):
per-test fresh tenant registries, patched lifespan, temp DATA_DIR.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import riks_context_engine.api.server as server_module
from riks_context_engine.api.server import _tenant_memory_registry, _tenant_registry, app
from riks_context_engine.chat_context import build_context_block, estimate_tokens

MODEL = "gemma4:31b"

TENANT_A = {"X-Tenant-Id": "cw168-tenant-a", "X-API-Key": "test-api-key"}
TENANT_B = {"X-Tenant-Id": "cw168-tenant-b", "X-API-Key": "test-api-key"}

#: The old ECHO MODE stub pattern from server.py (pre-#165). Any reply
#: containing this is a regression to unconditional echo mode.
ECHO_MODE_PATTERN = "Context engine entegrasyonu yakında aktif olacak"


@pytest.fixture(autouse=True)
def _fresh_tenant_stores(tmp_path, monkeypatch):
    """Fresh tenant-scoped context/memory registries per test.

    Same pattern as tests/test_api/test_memory_roundtrip_e2e.py: patch the
    lifespan (which creates the singletons) and clear the tenant-scoped
    registries so no state leaks between tests.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _tenant_registry._managers.clear()
    _tenant_memory_registry._semantic.clear()
    _tenant_memory_registry._episodic.clear()
    _tenant_memory_registry._procedural.clear()
    _tenant_memory_registry._data_dir = str(tmp_path)

    async def _fresh_lifespan(_app: Any):
        yield

    monkeypatch.setattr(server_module, "lifespan", _fresh_lifespan)
    server_module.API_KEY = "test-api-key"
    try:
        yield
    finally:
        _tenant_registry._managers.clear()
        _tenant_memory_registry._semantic.clear()
        _tenant_memory_registry._episodic.clear()
        _tenant_memory_registry._procedural.clear()


@pytest.fixture
def client():
    with TestClient(app, headers=TENANT_A) as c:
        yield c


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _chat(client: TestClient, headers: dict[str, str], message: str) -> dict[str, Any]:
    r = client.post("/api/chat", json={"message": message, "model": MODEL}, headers=headers)
    assert r.status_code == 200, f"unexpected status {r.status_code}: {r.text}"
    return r.json()


def _list_messages(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    r = client.get("/api/v1/context/messages", headers=headers)
    assert r.status_code == 200, f"unexpected status {r.status_code}: {r.text}"
    return r.json()


def _summary(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    r = client.get("/api/v1/context/summary", headers=headers)
    assert r.status_code == 200, f"unexpected status {r.status_code}: {r.text}"
    return r.json()


def _assert_not_echo_mode(reply: str) -> None:
    """Hard red/green guard: ECHO MODE stub pattern must never appear."""
    assert ECHO_MODE_PATTERN not in reply, (
        f"ECHO MODE stub detected in reply — /api/chat is not context-wired: {reply!r}"
    )


def _capture_last_prompt_block(client: TestClient, message: str) -> str:
    """Capture the exact prompt context block /api/chat builds for one call.

    Wraps the ``build_context_block`` name in the server module (server.py
    resolves it at call time) so this observes the real per-request prompt
    assembly — not a post-hoc rebuild.
    """
    captured: list[str] = []
    original = server_module.build_context_block

    def spy(*args: Any, **kwargs: Any) -> str:
        block = original(*args, **kwargs)
        captured.append(block)
        return block

    server_module.build_context_block = spy
    try:
        _chat(client, TENANT_A, message)
    finally:
        server_module.build_context_block = original
    assert captured, "build_context_block was not called by /api/chat"
    return captured[0]


# ─── 1. Last-N behavior ──────────────────────────────────────────────────────


class TestLastNBehavior:
    def test_only_most_recent_n_messages_in_context_block(self, client: TestClient):
        """AC1a: N=3 block from a 7-message window keeps only the last 3."""
        for i in range(1, 8):
            client.post(
                "/api/v1/context/messages",
                json={"role": "user", "content": f"mesaj-{i}"},
                headers=TENANT_A,
            )

        ctx = _tenant_registry.get("cw168-tenant-a")
        sem = _tenant_memory_registry.get_semantic("cw168-tenant-a")
        block = build_context_block(ctx, sem, "hala hatırlıyor musun?", max_messages=3)

        recent = [f"mesaj-{i}" for i in (5, 6, 7)]
        for msg in recent:
            assert msg in block, f"recent message {msg!r} missing from block: {block!r}"
        for old in (f"mesaj-{i}" for i in (1, 2, 3, 4)):
            assert old not in block, f"older message {old!r} leaked into N=3 block: {block!r}"

    def test_last_n_via_chat_endpoint(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """AC1a (HTTP-level): with a 3-message window, the prompt block
        /api/chat actually assembles holds only the LAST 3 messages —
        seeded messages older than the window never reach the prompt.

        N is pinned by patching the module-level config
        (CHAT_CONTEXT_MAX_MESSAGES) that build_context_block reads at call
        time, mirroring the env-overridable production config.
        """
        monkeypatch.setattr("riks_context_engine.chat_context.CHAT_CONTEXT_MAX_MESSAGES", 3)
        # Seed A's context with 5 messages, then /api/chat adds the new
        # exchange (user + assistant) → 7 messages total. The last-N=3
        # block can only hold the newest 3: the two newest seeded messages
        # must be visible, the 3 oldest must not.
        contents = [
            "eski-bir",
            "eski-iki",
            "Benim adım Vahit",
            "ortadaki-konu",
            "en-yeni-konu",
        ]
        for c in contents:
            client.post(
                "/api/v1/context/messages",
                json={"role": "user", "content": c},
                headers=TENANT_A,
            )
        assert len(_list_messages(client, TENANT_A)) == 5

        # Capture the EXACT block the first /api/chat call assembled
        # (before its own exchange is appended).
        block = _capture_last_prompt_block(client, "son ne konuştuk?")
        assert len(_list_messages(client, TENANT_A)) == 7  # + user + assistant

        assert "en-yeni-konu" in block
        assert "ortadaki-konu" in block
        assert "Benim adım Vahit" in block  # exactly at the 3-message boundary
        for m in ("eski-bir", "eski-iki"):
            assert m not in block, f"{m!r} leaked into the last-N block: {block!r}"


# ─── 2. Token-budget truncation (newest kept, oldest dropped, no error) ─────


class TestTokenBudgetTruncation:
    def test_old_messages_truncated_newest_kept_no_error(self, client: TestClient):
        """AC2: 6 messages over a tiny budget → oldest dropped first,
        newest kept, and build_context_block raises nothing."""
        for i in range(1, 7):
            client.post(
                "/api/v1/context/messages",
                json={
                    "role": "user",
                    "content": f"uzun-mesaj-{i} " + "x" * 60,  # ~15 tokens each
                },
                headers=TENANT_A,
            )

        ctx = _tenant_registry.get("cw168-tenant-a")
        sem = _tenant_memory_registry.get_semantic("cw168-tenant-a")
        # Budget comfortably below 6 messages (content-only), above 1.
        block = build_context_block(ctx, sem, "bütçe testi", max_tokens=40)

        assert "uzun-mesaj-6" in block, f"newest message must survive truncation: {block!r}"
        assert "uzun-mesaj-1" not in block, f"oldest message must be truncated first: {block!r}"
        # Content portion (between the fixed header and end) is within budget
        # (the returned block includes a fixed ~25-token instruction header
        # that build_context_block prepends after budgeting).
        content_part = block.split("## Recent conversation\n", 1)[1]
        assert estimate_tokens(content_part) <= 40, (
            f"truncated content still over budget: {estimate_tokens(content_part)} > 40"
        )

    def test_truncation_with_single_message_does_not_empty_block(self, client: TestClient):
        """AC2 edge: one giant message over budget → kept (newest), no error,
        non-empty block."""
        big = "dev-nesnesi " + "y" * 4000  # ~1000+ tokens, well over any budget
        client.post(
            "/api/v1/context/messages",
            json={"role": "user", "content": big},
            headers=TENANT_A,
        )

        ctx = _tenant_registry.get("cw168-tenant-a")
        sem = _tenant_memory_registry.get_semantic("cw168-tenant-a")
        # Must not raise, and must not produce an empty context block.
        block = build_context_block(ctx, sem, "tek mesaj", max_tokens=10)
        assert "dev-nesnesi" in block, "the single (newest) message must be kept"


# ─── 3. Tenant isolation ─────────────────────────────────────────────────────


class TestTenantIsolation:
    def test_b_cannot_see_a_context_messages(self, client: TestClient):
        """AC3: A posts a message; B's GET /api/v1/context/messages shows
        an empty window (no leak, no shared list)."""
        _chat(client, TENANT_A, "Benim gizli notum: kod-42")

        b_msgs = _list_messages(client, TENANT_B)
        assert b_msgs == [], f"tenant B sees A's context: {b_msgs!r}"
        assert _summary(client, TENANT_B)["messages_count"] == 0

    def test_b_chat_cannot_answer_from_a_context(self, client: TestClient):
        """AC3/AC2: A's 'Benim adım Vahit' is invisible to B — B's /api/chat
        must not answer 'Vahit' and must not echo A's context."""
        _chat(client, TENANT_A, "Benim adım Vahit")
        reply_b = _chat(client, TENANT_B, "Adım ne?")
        assert "Vahit" not in reply_b["response"], (
            f"tenant B answered from tenant A's context: {reply_b['response']!r}"
        )
        _assert_not_echo_mode(reply_b["response"])

    def test_wiping_b_never_touches_a(self, client: TestClient):
        """AC3: clearing B's tenant store (manager.reset) must not change
        A's context window at all (structural isolation, #102/#158)."""
        _chat(client, TENANT_A, "Benim adım Vahit")
        _chat(client, TENANT_B, "Benim adım Deniz")

        a_before = _list_messages(client, TENANT_A)
        assert len(a_before) == 2

        # B wipes its own context (what a tenant cleanup would do).
        _tenant_registry.get("cw168-tenant-b").reset()

        a_after = _list_messages(client, TENANT_A)
        assert a_after == a_before, (
            "tenant B's wipe changed tenant A's context — isolation violated"
        )
        assert _summary(client, TENANT_B)["messages_count"] == 0
        assert "Vahit" in " ".join(m["content"] for m in a_after)


# ─── 4. /api/chat tenant-scoped wiring (#158) ────────────────────────────────


class TestChatTenantScopedWiring:
    def test_chat_write_lands_in_tenant_a_manager_only(self, client: TestClient):
        """AC4: a /api/chat exchange under A is written to A's
        tenant-scoped ContextWindowManager (user + assistant), and B's
        manager stays empty."""
        reply = _chat(client, TENANT_A, "Benim adım Vahit")
        assert "Vahit" in reply["response"]

        a_mgr = _tenant_registry.get("cw168-tenant-a")
        a_contents = [m.content for m in a_mgr.get_messages(include_pruned=False)]
        assert "Benim adım Vahit" in a_contents
        assert any("Vahit" in c for c in a_contents), (
            "assistant reply was not written back into A's context window"
        )

        b_mgr = _tenant_registry.get("cw168-tenant-b")
        assert b_mgr.get_messages(include_pruned=False) == [], (
            "tenant A's exchange leaked into tenant B's context manager"
        )

    def test_chat_writes_are_tenant_scoped_via_http(self, client: TestClient):
        """AC4 (HTTP-only): the same exchange, verified through
        GET /api/v1/context/messages per tenant (no in-process access)."""
        _chat(client, TENANT_A, "Benim adım Vahit")

        a_msgs = _list_messages(client, TENANT_A)
        a_contents = " ".join(m["content"] for m in a_msgs)
        assert "Benim adım Vahit" in a_contents

        b_msgs = _list_messages(client, TENANT_B)
        assert b_msgs == []


# ─── 5. ECHO MODE red/green (#165) — unconditional, no skip/xfail ────────────


class TestEchoModeRedGreen:
    def test_chat_reply_is_context_aware_not_echo_stub(self, client: TestClient):
        """AC5: 'Benim adım Vahit' → 'Adım ne?' must be answered from
        context (Vahit, model-tagged) and NEVER with the old ECHO MODE
        stub pattern. Fails on the old staging image — by design."""
        first = _chat(client, TENANT_A, "Benim adım Vahit")
        _assert_not_echo_mode(first["response"])

        second = _chat(client, TENANT_A, "Adım ne?")
        reply = second["response"]
        _assert_not_echo_mode(reply)

        assert "Vahit" in reply, f"reply is not context-aware: {reply!r}"
        assert reply.startswith(f"[{MODEL}]"), f"reply must carry the model tag: {reply!r}"
