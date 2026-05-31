"""Redis-backed caching layer for HA replication.

Provides:
- L1 cache in front of SQLite/JSON storage
- Pub/sub for cross-instance context updates
- Write-through and write-back replication strategies
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class ReplicationStrategy(Enum):
    """How writes propagate from Redis cache to SQLite backend."""

    WRITE_THROUGH = "write_through"  # Write to both simultaneously
    WRITE_BACK = "write_back"  # Write to Redis, flush to SQLite on read or timer
    CACHE_ASIDE = "cache_aside"  # Read-through: check Redis first, fallback to SQLite


@dataclass
class CacheEntry:
    """A cached memory entry stored in Redis."""

    key: str
    value: str  # JSON serialized
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int | None = None
    dirty: bool = False  # Pending flush to backend


@dataclass
class ReplicationConfig:
    """Configuration for Redis cache and replication."""

    redis_url: str = "redis://localhost:6379/0"
    strategy: ReplicationStrategy = ReplicationStrategy.WRITE_THROUGH
    key_prefix: str = "riks:context:"
    channel: str = "riks:context:updates"
    ttl_seconds: int | None = 3600  # 1 hour default
    flush_interval_seconds: int = 30  # For write-back strategy
    max_queue_size: int = 1000  # Max pending write-back entries
    enable_pubsub: bool = True  # Broadcast updates via Redis pub/sub


class RedisCacheLayer:
    """L1 Redis cache with optional pub/sub for HA context replication.

    Wraps any storage backend (SQLite, JSON files) and adds:
    1. In-memory (Redis) caching for hot data
    2. Cross-instance synchronization via Redis pub/sub
    3. Configurable replication strategy

    Example:
        >>> cache = RedisCacheLayer(ReplicationConfig(redis_url="redis://localhost:6379/0"))
        >>> await cache.set("session:123", {"role": "user", "content": "Hello"})
        >>> data = await cache.get("session:123")
        >>> await cache.publish_update({"type": "context_update", "session_id": "123"})
    """

    def __init__(self, config: ReplicationConfig | None = None):
        self.config = config or ReplicationConfig()
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._subscriber_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._pending_writes: dict[str, CacheEntry] = {}
        self._write_lock = asyncio.Lock()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establish Redis connection and start background tasks.

        Returns:
            True if connected successfully, False otherwise.
        """
        if self._connected:
            return True

        try:
            self._redis = redis.from_url(
                self.config.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()

            if self.config.enable_pubsub:
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(self.config.channel)
                self._subscriber_task = asyncio.create_task(self._listen_pubsub())

            if self.config.strategy == ReplicationStrategy.WRITE_BACK:
                self._flush_task = asyncio.create_task(self._flush_loop())

            self._connected = True
            logger.info(f"Redis cache connected: {self.config.redis_url}")
            return True

        except Exception as e:
            logger.warning(f"Redis connection failed ({e}), running without cache")
            self._redis = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Gracefully disconnect and stop background tasks."""
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()

        if self._redis:
            await self._redis.close()

        self._connected = False
        logger.info("Redis cache disconnected")

    async def is_connected(self) -> bool:
        """Check if Redis is connected and healthy."""
        if not self._redis:
            return False
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Cache operations (get/set/delete)
    # ------------------------------------------------------------------

    def _make_key(self, key: str) -> str:
        """Prefix a cache key."""
        return f"{self.config.key_prefix}{key}"

    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a value from Redis cache.

        On cache miss with write-back strategy, checks pending writes first.

        Returns:
            Deserialized dict or None if not found.
        """
        if not self._redis:
            return None

        # Check pending writes first (write-back)
        if self.config.strategy == ReplicationStrategy.WRITE_BACK:
            pending = self._pending_writes.get(self._make_key(key))
            if pending:
                return json.loads(pending.value)

        try:
            full_key = self._make_key(key)
            raw = await self._redis.get(full_key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Redis GET failed for {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """Store a value in Redis cache.

        Args:
            key: Cache key (without prefix)
            value: JSON-serializable dict
            ttl: Override TTL in seconds (uses config default if None)

        Returns:
            True if stored successfully.
        """
        if not self._redis:
            return False

        try:
            full_key = self._make_key(key)
            serialized = json.dumps(value, default=str)
            ttl_ttl = ttl if ttl is not None else self.config.ttl_seconds

            if ttl_ttl:
                await self._redis.setex(full_key, ttl_ttl, serialized)
            else:
                await self._redis.set(full_key, serialized)

            # For write-back: queue for later flush
            if self.config.strategy == ReplicationStrategy.WRITE_BACK:
                async with self._write_lock:
                    self._pending_writes[full_key] = CacheEntry(
                        key=full_key,
                        value=serialized,
                        dirty=True,
                        ttl_seconds=ttl_ttl,
                    )
                    # Evict oldest if over queue limit
                    while len(self._pending_writes) > self.config.max_queue_size:
                        oldest_key = next(iter(self._pending_writes))
                        del self._pending_writes[oldest_key]

            return True
        except Exception as e:
            logger.warning(f"Redis SET failed for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Remove a key from Redis cache."""
        if not self._redis:
            return False

        try:
            full_key = self._make_key(key)
            await self._redis.delete(full_key)

            async with self._write_lock:
                self._pending_writes.pop(full_key, None)

            return True
        except Exception as e:
            logger.warning(f"Redis DELETE failed for {key}: {e}")
            return False

    async def clear_prefix(self, prefix: str) -> int:
        """Delete all keys matching a prefix pattern.

        Returns:
            Number of keys deleted.
        """
        if not self._redis:
            return 0

        try:
            full_pattern = f"{self.config.key_prefix}{prefix}*"
            keys = []
            async for key in self._redis.scan_iter(match=full_pattern):
                keys.append(key)

            if keys:
                return await self._redis.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Redis CLEAR_PREFIX failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # Pub/sub for cross-instance updates
    # ------------------------------------------------------------------

    async def publish_update(self, update: dict[str, Any]) -> bool:
        """Broadcast a context update to all subscribed instances.

        Args:
            update: Dict with keys like "type", "session_id", "data"

        Returns:
            True if published successfully.
        """
        if not self._redis or not self.config.enable_pubsub:
            return False

        try:
            import uuid

            update["_id"] = str(uuid.uuid4())
            update["_ts"] = datetime.now(timezone.utc).isoformat()
            payload = json.dumps(update, default=str)
            await self._redis.publish(self.config.channel, payload)
            return True
        except Exception as e:
            logger.warning(f"Redis PUBLISH failed: {e}")
            return False

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a local callback for pub/sub updates.

        Args:
            callback: Async or sync function that receives update dicts.
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Remove a previously registered callback."""
        self._subscribers.remove(callback)

    async def _listen_pubsub(self) -> None:
        """Background task: relay Redis pub/sub messages to local subscribers."""
        if not self._pubsub:
            return

        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    for cb in self._subscribers:
                        try:
                            result = cb(data)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.warning(f"Pub/sub callback error: {e}")
                except json.JSONDecodeError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Pub/sub listener error: {e}")

    # ------------------------------------------------------------------
    # Write-back flush loop
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Background task: periodically flush pending writes to backend."""
        while True:
            try:
                await asyncio.sleep(self.config.flush_interval_seconds)
                await self._flush_pending()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Flush loop error: {e}")

    async def _flush_pending(self) -> None:
        """Flush all pending write-back entries to the backend callback."""
        async with self._write_lock:
            entries = list(self._pending_writes.values())
            self._pending_writes.clear()

        for entry in entries:
            if self._on_flush:
                try:
                    await self._on_flush(entry.key, json.loads(entry.value))
                except Exception as e:
                    logger.warning(f"Flush failed for {entry.key}: {e}")
                    # Re-queue failed entries
                    async with self._write_lock:
                        self._pending_writes[entry.key] = entry

    # ------------------------------------------------------------------
    # Backend callback (set by ReplicationManager)
    # ------------------------------------------------------------------

    _on_flush: Callable[[str, dict[str, Any]], Any] | None = None

    def set_flush_callback(
        self, callback: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        """Set the callback invoked when write-back entries are flushed."""
        self._on_flush = callback

    # ------------------------------------------------------------------
    # Health and stats
    # ------------------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dict with hit/miss counts, memory usage, connection status.
        """
        stats: dict[str, Any] = {
            "connected": await self.is_connected(),
            "strategy": self.config.strategy.value,
            "pending_writes": len(self._pending_writes),
            "subscribers": len(self._subscribers),
        }

        if self._redis and stats["connected"]:
            try:
                info = await self._redis.info("memory")
                stats["used_memory_human"] = info.get("used_memory_human", "unknown")
            except Exception:
                pass

        return stats
