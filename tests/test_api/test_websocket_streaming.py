"""Tests for WebSocket context streaming (issue #106)."""

from __future__ import annotations

import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import (
    WebSocketContextStreamer,
    WSContextUpdate,
    WSClientMessage,
    app,
)


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset module-level state before each test."""
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    server_module._ws_streamer = None
    yield
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    server_module._ws_streamer = None


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
