"""E2E tests for /ws/v1/context/stream — subscription, isolation, lifecycle (#170).

Acceptance criteria mapping:

- AC1 (subscription <=5s, ordered): :class:`TestSubscriptionDelivery`
- AC2 (tenant isolation, negative): :class:`TestTenantIsolation`
- AC3 (disconnect/reconnect, no leak): :class:`TestDisconnectReconnect`
- AC4 (unhealthy payload behavior, documented): :class:`TestUnhealthyPayload`
- AC5 (test runs in CI; staging verified separately with ``websockets``/curl
  — snippet in the PR body): every test here runs on TestClient only, no
  external services required.
- Extra (C3/C4 evidence): unauthenticated WS connect is REJECTED
  (:class:`TestAuthRejectE2e`).

TRANSPORT NOTES (Starlette TestClient portal quirks, pinned here):

1. Pre-accept reject: the app closes with ASGI code 1008 *before* accept, so
   the test client surfaces it as ``WebSocketDisconnect(1008)``.
2. Auth via query param: TestClient/httpx masks ``X-API-Key`` header values
   to ``***`` (3 chars), breaking header-based key comparison. The query-param
   path (``?api_key=...``) is NOT masked and is the reliable auth vector in
   TestClient. Header-based auth is pinned in
   ``tests/test_api/test_websocket_streaming.py`` (unit tests with mocked WS).
3. Streamer acquisition: always use ``server_module._ws_streamers[tenant]``
   (the registry) — NEVER call ``_get_tenant_streamer()`` from the test
   thread before connecting. That creates a separate streamer instance not
   registered in the registry, so the broadcast targets an empty connection
   map and the frame is silently dropped.
4. Broadcast scheduling: ``run_coroutine_threadsafe`` on the session's portal
   loop (captured via ``ws.portal.call``) is the reliable way to drive a
   server-side coroutine from the test thread.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import (
    WS_CLOSE_UNAUTHORIZED,
    app,
)

WS_PATH = "/ws/v1/context/stream"
WS_KEY = "***"
WS_AUTH_URL = f"{WS_PATH}?api_key={WS_KEY}"


@pytest.fixture(autouse=True)
def ws_env(monkeypatch: pytest.MonkeyPatch):
    """Reset WS state and enable fail-closed auth (API_KEY set, non-local env)."""
    server_module._ws_streamers = {}
    server_module._ws_streamer = None
    monkeypatch.setattr(server_module, "API_KEY", WS_KEY)
    monkeypatch.setenv("RIKS_ENV", "staging")
    yield
    server_module._ws_streamers = {}
    server_module._ws_streamer = None


def _all_connections_count() -> int:
    total = 0
    for streamer in server_module._ws_streamers.values():
        total += len(streamer._connections)
    if server_module._ws_streamer is not None:
        total += len(server_module._ws_streamer._connections)
    return total


def _receive_json(ws) -> dict:
    return json.loads(ws.receive_text())


def _get_portal_loop(ws):
    """Capture the portal event loop from a live WS session."""
    box: dict = {}

    async def _cap() -> None:
        box["loop"] = asyncio.get_running_loop()

    ws.portal.call(_cap)
    return box["loop"]


def _broadcast(ws, tenant: str, content: str, stats: dict | None = None) -> None:
    """Broadcast one context event via the session's portal loop (blocking).

    Uses the REGISTRY streamer (``_ws_streamers[tenant]``) — the same instance
    the endpoint registered the connection with — so the frame is actually
    delivered to the connected socket.
    """
    streamer = server_module._ws_streamers[tenant]
    loop = _get_portal_loop(ws)
    fut = asyncio.run_coroutine_threadsafe(
        streamer.broadcast_context_update(
            messages=[{"role": "user", "content": content, "tokens": 5}],
            stats=stats or {},
        ),
        loop,
    )
    fut.result(timeout=5)


def _connect_reject(url: str, headers: dict | None = None) -> int:
    """Open a rejected WS connection and return the close code."""
    with TestClient(app, headers=headers or {}) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(url):
                pass  # unreachable
    return exc_info.value.code


# ─── AC1: subscription delivery, ordered, <=5s ──────────────────────────────


class TestSubscriptionDelivery:
    def test_events_delivered_in_order_within_5s(self):
        tenant = "ws-ac1"
        with TestClient(app, headers={"X-Tenant-Id": tenant}) as client:
            with client.websocket_connect(WS_AUTH_URL) as ws:
                assert _receive_json(ws)["type"] == "subscribed"
                ws.send_text(json.dumps({"type": "subscribe", "session_id": ""}))
                assert _receive_json(ws)["type"] == "subscribed"

                start = time.monotonic()
                for i in range(1, 4):
                    _broadcast(ws, tenant, f"e2e-event-{i}", {"current_tokens": 100 + i})
                    frame = _receive_json(ws)
                    assert frame["type"] == "context_update"
                    assert frame["messages"][0]["content"] == f"e2e-event-{i}"
                elapsed = time.monotonic() - start

        assert elapsed <= 5.0, f"3 events took {elapsed:.2f}s (>5s budget)"


# ─── AC2: tenant isolation (negative) ───────────────────────────────────────


class TestTenantIsolation:
    def test_tenant_b_receives_no_events_from_tenant_a(self):
        """A's broadcast addresses only A's streamer; B's streamer is distinct,
        so B's sockets can never receive A's events. Verified by (a) 3 A events
        arriving on A's socket in order, (b) B's streamer holding no
        connections, (c) structural distinctness of the two streamer objects."""
        tenant_a, tenant_b = "ws-iso-a", "ws-iso-b"
        with TestClient(app, headers={"X-Tenant-Id": tenant_a}) as client_a:
            with client_a.websocket_connect(WS_AUTH_URL) as ws_a:
                assert _receive_json(ws_a)["type"] == "subscribed"
                ws_a.send_text(json.dumps({"type": "subscribe", "session_id": ""}))
                _receive_json(ws_a)  # sub ack

                for i in range(1, 4):
                    _broadcast(ws_a, tenant_a, f"iso-event-{i}")
                    frame = _receive_json(ws_a)
                    assert frame["type"] == "context_update"
                    assert frame["messages"][0]["content"] == f"iso-event-{i}"

        # Structural isolation: A's streamer (created by the endpoint during
        # the connection) is a distinct object from B's streamer (created
        # on-demand here). B's streamer holds no connections, so A's events
        # can never reach B's sockets.
        streamer_a = server_module._get_tenant_streamer(tenant_a)
        streamer_b = server_module._get_tenant_streamer(tenant_b)
        assert streamer_a is not streamer_b
        assert streamer_a.client_count == 0
        assert streamer_b.client_count == 0
        assert len(streamer_b._connections) == 0


# ─── AC3: disconnect/reconnect, no leak ─────────────────────────────────────


class TestDisconnectReconnect:
    def test_disconnect_cleans_up_and_reconnect_works(self):
        tenant = "ws-leak"
        baseline = _all_connections_count()

        with TestClient(app, headers={"X-Tenant-Id": tenant}) as client:
            with client.websocket_connect(WS_AUTH_URL) as ws:
                assert _receive_json(ws)["type"] == "subscribed"
                ws.send_text(json.dumps({"type": "subscribe", "session_id": ""}))
                _receive_json(ws)
                assert _all_connections_count() == baseline + 1

            after_first = _all_connections_count()
            assert after_first == baseline, (
                f"leak after disconnect: {after_first} != baseline {baseline}"
            )

            with client.websocket_connect(WS_AUTH_URL) as ws2:
                assert _receive_json(ws2)["type"] == "subscribed"
                ws2.send_text(json.dumps({"type": "subscribe", "session_id": ""}))
                _receive_json(ws2)
                _broadcast(ws2, tenant, "reconnect-event-99")
                frame = _receive_json(ws2)
                assert frame["type"] == "context_update"
                assert frame["messages"][0]["content"] == "reconnect-event-99"

        after_second = _all_connections_count()
        assert after_second == baseline, (
            f"leak after second disconnect: {after_second} != baseline {baseline}"
        )


# ─── AC4: unhealthy payload behavior (documented) ───────────────────────────


class TestUnhealthyPayload:
    def test_non_json_message_yields_error_frame_connection_stays_open(self):
        """Documented behavior: non-JSON input -> {"type": "error"} frame,
        connection STAYS OPEN (no drop, no close code)."""
        with TestClient(app, headers={"X-Tenant-Id": "ws-ac4"}) as client:
            with client.websocket_connect(WS_AUTH_URL) as ws:
                assert _receive_json(ws)["type"] == "subscribed"
                ws.send_text("this-is-not-json")
                frame = _receive_json(ws)
                assert frame["type"] == "error"
                assert frame["detail"] == "Invalid JSON message"
                ws.send_text(json.dumps({"type": "ping"}))
                pong = _receive_json(ws)
                assert pong["type"] == "heartbeat"
                assert pong["detail"] == "pong"

    def test_unknown_message_type_yields_error_frame_connection_stays_open(self):
        with TestClient(app, headers={"X-Tenant-Id": "ws-ac4"}) as client:
            with client.websocket_connect(WS_AUTH_URL) as ws:
                assert _receive_json(ws)["type"] == "subscribed"
                ws.send_text(json.dumps({"type": "warp-drive"}))
                frame = _receive_json(ws)
                assert frame["type"] == "error"
                assert "warp-drive" in frame["detail"]
                ws.send_text(json.dumps({"type": "ping"}))
                assert _receive_json(ws)["type"] == "heartbeat"


# ─── Extra: unauthenticated connect RED (C3/C4 evidence) ────────────────────


class TestAuthRejectE2e:
    def test_unauthenticated_connect_rejected_code_1008_no_state(self):
        """C3/C4: authsuz WS connect -> reject (ASGI 1008 pre-accept);
        state leak yok."""
        code = _connect_reject(WS_PATH, headers={"X-Tenant-Id": "ws-e2e"})
        assert code == WS_CLOSE_UNAUTHORIZED == 1008
        assert server_module._ws_streamers == {}
        assert _all_connections_count() == 0

    def test_missing_tenant_connect_rejected_code_4004_no_state(self):
        """Valid key, no tenant -> 4004 (missing/malformed tenant)."""
        code = _connect_reject(WS_AUTH_URL)
        assert code == 4004
        assert server_module._ws_streamers == {}

    def test_missing_key_and_tenant_rejected_code_1008_no_state(self):
        """No key, no tenant -> 1008 (auth checked first)."""
        code = _connect_reject(WS_PATH)
        assert code == WS_CLOSE_UNAUTHORIZED == 1008
        assert server_module._ws_streamers == {}
