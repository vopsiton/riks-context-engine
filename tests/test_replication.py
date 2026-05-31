"""Tests for Redis cache layer and ReplicationManager."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from riks_context_engine.storage.redis_cache import (
    CacheEntry,
    ReplicationConfig,
    ReplicationStrategy,
    RedisCacheLayer,
)
from riks_context_engine.storage.replication import ReplicationManager


# ------------------------------------------------------------------
# RedisCacheLayer tests
# ------------------------------------------------------------------

class TestRedisCacheLayerConfig:
    """Test ReplicationConfig defaults and validation."""

    def test_default_config(self):
        config = ReplicationConfig()
        assert config.redis_url == "redis://localhost:6379/0"
        assert config.strategy == ReplicationStrategy.WRITE_THROUGH
        assert config.key_prefix == "riks:context:"
        assert config.channel == "riks:context:updates"
        assert config.ttl_seconds == 3600
        assert config.enable_pubsub is True

    def test_custom_config(self):
        config = ReplicationConfig(
            redis_url="redis://redis.example.com:6380/1",
            strategy=ReplicationStrategy.WRITE_BACK,
            ttl_seconds=7200,
            enable_pubsub=False,
        )
        assert config.redis_url == "redis://redis.example.com:6380/1"
        assert config.strategy == ReplicationStrategy.WRITE_BACK
        assert config.ttl_seconds == 7200
        assert config.enable_pubsub is False


class TestRedisCacheLayerUnit:
    """Unit tests for RedisCacheLayer without requiring a real Redis instance."""

    def test_make_key(self):
        config = ReplicationConfig(key_prefix="test:")
        layer = RedisCacheLayer(config)
        assert layer._make_key("foo") == "test:foo"
        assert layer._make_key("session:42") == "test:session:42"

    def test_initial_state_disconnected(self):
        layer = RedisCacheLayer()
        assert layer._connected is False
        assert layer._redis is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_disconnected(self):
        layer = RedisCacheLayer()
        result = await layer.get("any_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_returns_false_when_disconnected(self):
        layer = RedisCacheLayer()
        result = await layer.set("key", {"data": "value"})
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_disconnected(self):
        layer = RedisCacheLayer()
        result = await layer.delete("key")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_connected_false_when_no_redis(self):
        layer = RedisCacheLayer()
        assert await layer.is_connected() is False

    @pytest.mark.asyncio
    async def test_stats_when_disconnected(self):
        layer = RedisCacheLayer()
        stats = await layer.stats()
        assert stats["connected"] is False
        assert stats["strategy"] == "write_through"
        assert stats["pending_writes"] == 0

    def test_subscribe_unsubscribe(self):
        layer = RedisCacheLayer()
        cb = MagicMock()
        layer.subscribe(cb)
        assert cb in layer._subscribers
        layer.unsubscribe(cb)
        assert cb not in layer._subscribers

    def test_subscribe_multiple_callbacks(self):
        layer = RedisCacheLayer()
        cb1 = MagicMock()
        cb2 = MagicMock()
        layer.subscribe(cb1)
        layer.subscribe(cb2)
        assert len(layer._subscribers) == 2
        layer.unsubscribe(cb1)
        assert len(layer._subscribers) == 1
        assert cb2 in layer._subscribers


class TestRedisCacheLayerWithMock:
    """Tests using async mocks for Redis operations."""

    @pytest.mark.asyncio
    async def test_set_with_mock_redis(self):
        config = ReplicationConfig(redis_url="redis://localhost:6379/0")
        layer = RedisCacheLayer(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.set = AsyncMock(return_value=True)

        layer._redis = mock_redis
        layer._connected = True

        result = await layer.set("session:1", {"role": "user", "content": "Hello"})
        assert result is True
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "riks:context:session:1"

    @pytest.mark.asyncio
    async def test_get_with_mock_redis_hit(self):
        config = ReplicationConfig()
        layer = RedisCacheLayer(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=json.dumps({"role": "assistant", "content": "Hi"}))

        layer._redis = mock_redis
        layer._connected = True

        result = await layer.get("session:1")
        assert result == {"role": "assistant", "content": "Hi"}

    @pytest.mark.asyncio
    async def test_get_with_mock_redis_miss(self):
        config = ReplicationConfig()
        layer = RedisCacheLayer(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)

        layer._redis = mock_redis
        layer._connected = True

        result = await layer.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_with_mock_redis(self):
        config = ReplicationConfig()
        layer = RedisCacheLayer(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=1)

        layer._redis = mock_redis
        layer._connected = True

        result = await layer.delete("session:1")
        assert result is True
        mock_redis.delete.assert_called_once_with("riks:context:session:1")

    @pytest.mark.asyncio
    async def test_publish_update(self):
        config = ReplicationConfig(enable_pubsub=True)
        layer = RedisCacheLayer(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.publish = AsyncMock(return_value=1)

        layer._redis = mock_redis
        layer._connected = True

        result = await layer.publish_update({
            "type": "context_update",
            "session_id": "s1",
            "data": {"role": "user"},
        })
        assert result is True
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args[0]
        assert call_args[0] == "riks:context:updates"
        published = json.loads(call_args[1])
        assert published["type"] == "context_update"
        assert published["session_id"] == "s1"


# ------------------------------------------------------------------
# ReplicationManager tests
# ------------------------------------------------------------------

class TestReplicationManager:
    """Tests for ReplicationManager."""

    def test_default_construction(self):
        manager = ReplicationManager()
        assert manager.config.redis_url == "redis://localhost:6379/0"
        assert manager.cache is not None
        assert manager._semantic_memory is None
        assert manager._episodic_memory is None
        assert manager._context_manager is None

    def test_custom_config(self):
        config = ReplicationConfig(
            strategy=ReplicationStrategy.WRITE_BACK,
            ttl_seconds=7200,
        )
        manager = ReplicationManager(config)
        assert manager.config.strategy == ReplicationStrategy.WRITE_BACK

    @pytest.mark.asyncio
    async def test_start_disconnected(self):
        """Start without Redis should still work (cache disabled)."""
        manager = ReplicationManager()
        # Mock connect to fail
        with patch.object(manager.cache, "connect", AsyncMock(return_value=False)):
            result = await manager.start()
        assert result is False
        assert manager._started is True

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        manager = ReplicationManager()
        await manager.stop()  # Should not raise
        assert manager._started is False

    @pytest.mark.asyncio
    async def test_health_check(self):
        manager = ReplicationManager()
        with patch.object(manager.cache, "is_connected", AsyncMock(return_value=False)):
            with patch.object(manager.cache, "stats", AsyncMock(return_value={"connected": False})):
                health = await manager.health_check()
        assert health["cache"]["connected"] is False
        assert health["semantic_registered"] is False
        assert health["episodic_registered"] is False
        assert health["context_registered"] is False

    @pytest.mark.asyncio
    async def test_broadcast_context_update_no_redis(self):
        manager = ReplicationManager()
        manager.cache._connected = False
        result = await manager.broadcast_context_update("s1", {"role": "user"})
        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_pruning_event(self):
        manager = ReplicationManager()
        with patch.object(manager.cache, "publish_update", AsyncMock(return_value=True)) as mock_pub:
            result = await manager.broadcast_pruning_event(
                session_id="s1",
                pruned_count=3,
                reason="token_limit",
            )
        assert result is True
        mock_pub.assert_called_once()
        call_args = mock_pub.call_args[0][0]
        assert call_args["type"] == "pruning_event"
        assert call_args["pruned_count"] == 3

    def test_entry_to_dict_from_dataclass(self):
        from dataclasses import dataclass

        @dataclass
        class DummyEntry:
            id: str
            name: str
            score: float = 0.5

        entry = DummyEntry(id="e1", name="test", score=0.9)
        result = ReplicationManager._entry_to_dict(entry)
        assert result == {"id": "e1", "name": "test", "score": 0.9}


class TestSemanticEntrySerialization:
    """Test SemanticEntry dict serialization used by ReplicationManager."""

    def test_semantic_entry_to_dict(self):
        from riks_context_engine.memory.semantic import SemanticEntry

        now = datetime.now(timezone.utc)
        entry = SemanticEntry(
            id="sm_123",
            subject="test_subject",
            predicate="relates_to",
            object="test_object",
            confidence=0.85,
            created_at=now,
            last_accessed=now,
            access_count=5,
            embedding=[0.1, 0.2, 0.3],
        )
        result = ReplicationManager._entry_to_dict(entry)
        assert result["id"] == "sm_123"
        assert result["subject"] == "test_subject"
        assert result["confidence"] == 0.85


class TestEpisodicEntrySerialization:
    """Test EpisodicEntry dict serialization used by ReplicationManager."""

    def test_episodic_entry_to_dict(self):
        from riks_context_engine.memory.episodic import EpisodicEntry

        now = datetime.now(timezone.utc)
        entry = EpisodicEntry(
            id="ep_456",
            timestamp=now,
            content="test content",
            importance=0.7,
            tags=["test", "unit"],
            access_count=3,
        )
        result = ReplicationManager._entry_to_dict(entry)
        assert result["id"] == "ep_456"
        assert result["content"] == "test content"
        assert result["importance"] == 0.7
        assert result["tags"] == ["test", "unit"]
