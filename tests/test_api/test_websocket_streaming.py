"""Tests for WebSocket context streaming (issue #106).

Includes WS auth fail-closed tests (#170-prereq, P1): the handshake must
present a valid API key (X-API-Key header or ?api_key query) and a
well-formed tenant (X-Tenant-Id header or ?tenant_id query).
"""

from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocket

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import (
    WS_CLOSE_TENANT_REQUIRED,
    WS_CLOSE_UNAUTHORIZED,
    WebSocketContextStreamer,
    WSClientMessage,
    WSContextUpdate,
    app,
)


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset module-level state before each test."""
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    server_module._ws_streamer = None
    server_module._ws_streamers = {}
    yield
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    server_module._ws_streamer = None
    server_module._ws_streamers = {}


@pytest.fixture
def streamer():
    """Return a fresh WebSocketContextStreamer instance."""
    return WebSocketContextStreamer()


# ─── WSClientMessage model tests ─────────────────────────────────────────────


class TestWSClientMessage:
    def test_subscribe_message(self):
        msg = WSClientMessage(type="subscribe", session_id="my-session")
        assert msg.type == "subscribe"
        assert msg.session_id == "my-session"
        assert msg.include_stats is True

    def test_unsubscribe_message(self):
        msg = WSClientMessage(type="unsubscribe")
        assert msg.type == "unsubscribe"

    def test_ping_message(self):
        msg = WSClientMessage(type="ping")
        assert msg.type == "ping"


# ─── WSContextUpdate model tests ─────────────────────────────────────────────


class TestWSContextUpdate:
    def test_context_update(self):
        update = WSContextUpdate(
            type="context_update",
            session_id="sess-1",
            messages=[{"id": "msg_1", "role": "user", "content": "hello"}],
            stats={"current_tokens": 10, "active_messages": 1},
            pruned_count=0,
        )
        assert update.type == "context_update"
        assert len(update.messages) == 1
        assert update.stats is not None

    def test_heartbeat(self):
        update = WSContextUpdate(type="heartbeat", detail="pong")
        assert update.type == "heartbeat"
        assert update.detail == "pong"

    def test_subscribed(self):
        update = WSContextUpdate(
            type="subscribed",
            session_id="my-session",
            detail="Subscribed to context updates for session: my-session",
        )
        assert update.type == "subscribed"
        assert "my-session" in update.detail

    def test_pruning_event(self):
        update = WSContextUpdate(
            type="pruning_event",
            pruned_count=3,
            stats={"current_tokens": 50000, "active_messages": 20},
            detail="Pruned 3 messages from context window",
        )
        assert update.type == "pruning_event"
        assert update.pruned_count == 3

    def test_error(self):
        update = WSContextUpdate(type="error", detail="Unknown message type")
        assert update.type == "error"
        assert update.detail == "Unknown message type"

    def test_default_timestamp(self):
        update = WSContextUpdate(type="heartbeat")
        assert update.timestamp.endswith("Z")


# ─── WebSocketContextStreamer unit tests ─────────────────────────────────────


class TestWebSocketContextStreamer:
    @pytest.mark.asyncio
    async def test_client_count_starts_at_zero(self, streamer):
        assert streamer.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_client_is_safe(self, streamer):
        # Should not raise
        await streamer.disconnect("nonexistent")

    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self, streamer):
        # Mock WebSocket - we test the subscription state directly
        class MockWebSocket:
            async def accept(self):
                pass

            async def send_text(self, text):
                pass

        ws = MockWebSocket()
        client_id = await streamer.connect(ws)
        assert streamer.client_count == 1

        # Subscribe
        await streamer.subscribe(client_id, "session-123")
        async with streamer._lock:
            assert streamer._subscriptions[client_id] == "session-123"

        # Unsubscribe
        await streamer.unsubscribe(client_id)
        async with streamer._lock:
            assert streamer._subscriptions[client_id] == ""

        await streamer.disconnect(client_id)
        assert streamer.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_all_subscribed(self, streamer):
        class MockWebSocket:
            def __init__(self):
                self.sent: list[str] = []

            async def accept(self):
                pass

            async def send_text(self, text):
                self.sent.append(text)

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        cid1 = await streamer.connect(ws1)
        cid2 = await streamer.connect(ws2)

        await streamer.subscribe(cid1, "")
        await streamer.subscribe(cid2, "")

        await streamer.broadcast_context_update(
            messages=[{"id": "msg_1", "role": "user", "content": "test"}],
            stats={"current_tokens": 10},
        )

        assert len(ws1.sent) == 2  # subscription ack + broadcast
        assert len(ws2.sent) == 2

        data1 = json.loads(ws1.sent[1])
        assert data1["type"] == "context_update"
        assert len(data1["messages"]) == 1

        await streamer.disconnect(cid1)
        await streamer.disconnect(cid2)

    @pytest.mark.asyncio
    async def test_broadcast_pruning_event(self, streamer):
        class MockWebSocket:
            def __init__(self):
                self.sent: list[str] = []

            async def accept(self):
                pass

            async def send_text(self, text):
                self.sent.append(text)

        ws = MockWebSocket()
        cid = await streamer.connect(ws)
        await streamer.subscribe(cid, "")

        await streamer.broadcast_pruning_event(pruned_count=5, stats={"current_tokens": 80000})

        # First message is subscription ack, second is pruning event
        assert len(ws.sent) == 2
        data = json.loads(ws.sent[1])
        assert data["type"] == "pruning_event"
        assert data["pruned_count"] == 5
        assert "Pruned 5 messages" in data["detail"]

        await streamer.disconnect(cid)

    @pytest.mark.asyncio
    async def test_handle_client_subscribe_message(self, streamer):
        class MockWebSocket:
            def __init__(self):
                self.sent: list[str] = []

            async def accept(self):
                pass

            async def send_text(self, text):
                self.sent.append(text)

        ws = MockWebSocket()
        cid = await streamer.connect(ws)

        # Send subscribe message
        msg = json.dumps({"type": "subscribe", "session_id": "my-session"}).encode()
        await streamer.handle_client_message(cid, msg)

        assert len(ws.sent) == 1  # subscription ack
        data = json.loads(ws.sent[0])
        assert data["type"] == "subscribed"
        assert data["session_id"] == "my-session"

        await streamer.disconnect(cid)

    @pytest.mark.asyncio
    async def test_handle_client_ping_message(self, streamer):
        class MockWebSocket:
            def __init__(self):
                self.sent: list[str] = []

            async def accept(self):
                pass

            async def send_text(self, text):
                self.sent.append(text)

        ws = MockWebSocket()
        cid = await streamer.connect(ws)

        # Send ping
        msg = json.dumps({"type": "ping"}).encode()
        await streamer.handle_client_message(cid, msg)

        assert len(ws.sent) == 1
        data = json.loads(ws.sent[0])
        assert data["type"] == "heartbeat"
        assert data["detail"] == "pong"

        await streamer.disconnect(cid)

    @pytest.mark.asyncio
    async def test_handle_client_invalid_json(self, streamer):
        class MockWebSocket:
            def __init__(self):
                self.sent: list[str] = []

            async def accept(self):
                pass

            async def send_text(self, text):
                self.sent.append(text)

        ws = MockWebSocket()
        cid = await streamer.connect(ws)

        # Send invalid JSON
        await streamer.handle_client_message(cid, b"not valid json{")

        assert len(ws.sent) == 1
        data = json.loads(ws.sent[0])
        assert data["type"] == "error"
        assert "Invalid JSON" in data["detail"]

        await streamer.disconnect(cid)

    @pytest.mark.asyncio
    async def test_handle_client_unknown_type(self, streamer):
        class MockWebSocket:
            def __init__(self):
                self.sent: list[str] = []

            async def accept(self):
                pass

            async def send_text(self, text):
                self.sent.append(text)

        ws = MockWebSocket()
        cid = await streamer.connect(ws)

        msg = json.dumps({"type": "unknown_type"}).encode()
        await streamer.handle_client_message(cid, msg)

        data = json.loads(ws.sent[0])
        assert data["type"] == "error"
        assert "Unknown message type" in data["detail"]

        await streamer.disconnect(cid)


# ─── WebSocket endpoint integration tests ─────────────────────────────────────


class TestWebSocketEndpoint:
    def test_websocket_endpoint_exists(self):
        """Verify the WebSocket route is registered."""
        routes = [r.path for r in app.routes]
        assert "/ws/v1/context/stream" in routes

    def test_app_version_updated(self):
        """Verify version was bumped to 0.4.0 for the sprint."""
        from riks_context_engine.api.server import app

        assert app.version == "0.4.0"


# ─── WS auth fail-closed (#170-prereq, P1) ─────────────────────────────────
#
# NOTE ON WIRE SEMANTICS: a pre-accept ``websocket.close()`` is translated by
# the ASGI server (uvicorn) into an HTTP 403 at the handshake — the custom
# close code (1008/4004) rides on the ASGI ``websocket.close`` message and is
# the contract pinned here. The wire-level 403 was verified with raw-socket
# probes against uvicorn (both ``ws=auto`` websockets protocol and default).


def _make_ws(scope: dict, sent: list) -> WebSocket:
    """Build a WebSocket test double capturing outgoing ASGI messages."""

    async def receive():
        raise RuntimeError("no data expected in auth unit tests")

    async def send(message: dict):
        sent.append(message)

    return WebSocket(scope=scope, receive=receive, send=send)


@pytest.mark.asyncio
class TestWSAuthFailClosedEndpoint:
    """Endpoint-level auth: reject before accept, no streamer state touched."""

    async def test_auth_via_header_accepted(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        sent: list[dict] = []
        ws = _make_ws(
            {
                "type": "websocket",
                "headers": [(b"x-api-key", b"k1"), (b"x-tenant-id", b"t1")],
                "query_string": b"",
            },
            sent,
        )
        accepted: list = []

        async def fake_accept():
            accepted.append(True)

        ws.accept = fake_accept
        await server_module.websocket_context_stream(ws)
        assert accepted, "valid credentials must reach accept()"
        assert any(m["type"] == "websocket.close" for m in sent) is False

    async def test_auth_via_query_param_accepted(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        sent: list[dict] = []
        ws = _make_ws(
            {"type": "websocket", "headers": [], "query_string": b"api_key=k1&tenant_id=t1"},
            sent,
        )
        accepted: list = []

        async def fake_accept():
            accepted.append(True)

        ws.accept = fake_accept
        await server_module.websocket_context_stream(ws)
        assert accepted, "query-param credentials must reach accept()"

    @pytest.mark.parametrize(
        "headers,query",
        [
            ([], b""),  # no key at all
            ([(b"x-api-key", b"wrong")], b""),  # wrong header key
            ([], b"api_key=wrong"),  # wrong query key
        ],
    )
    async def test_reject_auth_before_accept(self, monkeypatch: pytest.MonkeyPatch, headers, query):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        sent: list[dict] = []
        ws = _make_ws({"type": "websocket", "headers": headers, "query_string": query}, sent)

        async def _reject_accept(*a, **kw):
            pytest.fail("reject path must never call accept()")

        ws.accept = _reject_accept
        await server_module.websocket_context_stream(ws)
        # Exactly one ASGI close with the auth code, nothing else.
        assert sent == [
            {"type": "websocket.close", "code": WS_CLOSE_UNAUTHORIZED, "reason": "Unauthorized"}
        ]
        # C3: rejected connection never enters any streamer state.
        assert server_module._ws_streamers == {}
        assert server_module._ws_streamer is None

    @pytest.mark.parametrize(
        "headers,query",
        [
            ([], b""),  # missing tenant
            ([(b"x-tenant-id", b"")], b""),  # empty tenant header
            ([(b"x-tenant-id", b"bad tenant!")], b""),  # malformed tenant
            ([], b"tenant_id=%20"),  # malformed query tenant
        ],
    )
    async def test_reject_tenant_before_accept(
        self, monkeypatch: pytest.MonkeyPatch, headers, query
    ):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        ws = _make_ws(
            {"type": "websocket", "headers": headers, "query_string": query},
            sent := [],
        )
        # Valid key first, then invalid tenant -> tenant close code.
        if not any(k == b"x-api-key" for k, _ in headers):
            headers.append((b"x-api-key", b"k1"))

        async def _reject_accept(*a, **kw):
            pytest.fail("reject path must never call accept()")

        ws.accept = _reject_accept
        await server_module.websocket_context_stream(ws)
        assert sent == [
            {
                "type": "websocket.close",
                "code": WS_CLOSE_TENANT_REQUIRED,
                "reason": "Invalid or missing tenant",
            }
        ]
        assert server_module._ws_streamers == {}

    async def test_local_mode_open_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch):
        """RIKS_ENV=local + no API_KEY configured -> open (matches HTTP #166)."""
        monkeypatch.setattr(server_module, "API_KEY", "")
        monkeypatch.setenv("RIKS_ENV", "local")
        sent: list[dict] = []
        ws = _make_ws(
            {"type": "websocket", "headers": [(b"x-tenant-id", b"t-local")], "query_string": b""},
            sent,
        )
        accepted: list = []

        async def fake_accept():
            accepted.append(True)

        ws.accept = fake_accept
        await server_module.websocket_context_stream(ws)
        assert accepted

    async def test_no_api_key_rejected_outside_local(self, monkeypatch: pytest.MonkeyPatch):
        """No API_KEY + RIKS_ENV != local -> fail-closed reject."""
        monkeypatch.setattr(server_module, "API_KEY", "")
        monkeypatch.setenv("RIKS_ENV", "staging")
        sent: list[dict] = []
        ws = _make_ws(
            {"type": "websocket", "headers": [(b"x-tenant-id", b"t1")], "query_string": b""},
            sent,
        )

        async def _reject_accept(*a, **kw):
            pytest.fail("reject path must never call accept()")

        ws.accept = _reject_accept
        await server_module.websocket_context_stream(ws)
        assert sent == [
            {"type": "websocket.close", "code": WS_CLOSE_UNAUTHORIZED, "reason": "Unauthorized"}
        ]


class TestWSAuthHelpers:
    """Unit tests for the auth/tenant resolution helpers (code-level contract)."""

    async def test_authenticate_header_match(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        ws = _make_ws(
            {"type": "websocket", "headers": [(b"x-api-key", b"k1")], "query_string": b""}, []
        )
        assert server_module._ws_authenticate(ws) is True

    async def test_authenticate_query_match(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        ws = _make_ws({"type": "websocket", "headers": [], "query_string": b"api_key=k1"}, [])
        assert server_module._ws_authenticate(ws) is True

    async def test_authenticate_wrong_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(server_module, "API_KEY", "k1")
        ws = _make_ws(
            {"type": "websocket", "headers": [(b"x-api-key", b"k2")], "query_string": b""}, []
        )
        assert server_module._ws_authenticate(ws) is False

    async def test_tenant_from_header(self, monkeypatch: pytest.MonkeyPatch):
        ws = _make_ws(
            {"type": "websocket", "headers": [(b"x-tenant-id", b"tenant-1")], "query_string": b""},
            [],
        )
        assert server_module._ws_resolve_tenant(ws) == "tenant-1"

    async def test_tenant_from_query(self, monkeypatch: pytest.MonkeyPatch):
        ws = _make_ws(
            {"type": "websocket", "headers": [], "query_string": b"tenant_id=tenant-2"}, []
        )
        assert server_module._ws_resolve_tenant(ws) == "tenant-2"

    async def test_tenant_malformed_returns_none(self):
        ws = _make_ws(
            {
                "type": "websocket",
                "headers": [(b"x-tenant-id", b"bad tenant!")],
                "query_string": b"",
            },
            [],
        )
        assert server_module._ws_resolve_tenant(ws) is None

    async def test_tenant_missing_returns_none(self):
        ws = _make_ws({"type": "websocket", "headers": [], "query_string": b""}, [])
        assert server_module._ws_resolve_tenant(ws) is None

    def test_close_codes_are_standard(self):
        """Pin the convention: 1008 for auth (RFC standard), 4004 private-use."""
        assert WS_CLOSE_UNAUTHORIZED == 1008
        assert WS_CLOSE_TENANT_REQUIRED == 4004
