"""Replication manager — coordinates Redis cache with SQLite/JSON backends.

Provides HA replication for:
- SemanticMemory (SQLite) → Redis cache
- EpisodicMemory (JSON) → Redis cache
- ContextWindowManager → Redis pub/sub
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from riks_context_engine.storage.redis_cache import (
    CacheEntry,
    ReplicationConfig,
    ReplicationStrategy,
    RedisCacheLayer,
)

if TYPE_CHECKING:
    from riks_context_engine.context.manager import ContextMessage, ContextWindowManager
    from riks_context_engine.memory.episodic import EpisodicEntry, EpisodicMemory
    from riks_context_engine.memory.semantic import SemanticEntry, SemanticMemory

logger = logging.getLogger(__name__)


class ReplicationManager:
    """Orchestrates Redis caching and replication across memory tiers.

    Wraps existing SQLite/JSON backends with a Redis L1 cache and
    pub/sub for cross-instance context updates, providing HA replication.

    Usage:
        >>> config = ReplicationConfig(redis_url="redis://localhost:6379/0")
        >>> manager = ReplicationManager(config)
        >>> await manager.start()
        >>> manager.register_semantic(semantic_memory_instance)
        >>> manager.register_episodic(episodic_memory_instance)
        >>> manager.register_context(context_window_manager_instance)
    """

    def __init__(self, config: ReplicationConfig | None = None):
        self.config = config or ReplicationConfig()
        self.cache = RedisCacheLayer(self.config)
        self._semantic_memory: SemanticMemory | None = None
        self._episodic_memory: EpisodicMemory | None = None
        self._context_manager: ContextWindowManager | None = None
        self._started = False
        self._update_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Start the replication manager and connect to Redis.

        Returns:
            True if Redis connected (cache enabled), False otherwise.
        """
        if self._started:
            return await self.cache.is_connected()

        self.cache.set_flush_callback(self._on_flush_to_backend)
        connected = await self.cache.connect()
        self._started = True
        logger.info(f"ReplicationManager started (cache={'ON' if connected else 'OFF'})")
        return connected

    async def stop(self) -> None:
        """Stop the replication manager gracefully."""
        if not self._started:
            return

        # Flush pending writes before shutdown
        if self.config.strategy == ReplicationStrategy.WRITE_BACK:
            await self.cache._flush_pending()

        await self.cache.disconnect()
        self._started = False
        logger.info("ReplicationManager stopped")

    # ------------------------------------------------------------------
    # Registration of backend stores
    # ------------------------------------------------------------------

    def register_semantic(self, memory: SemanticMemory) -> None:
        """Register a SemanticMemory instance for cached replication.

        After registration, all reads go through Redis cache first,
        and writes use the configured replication strategy.

        Args:
            memory: A SemanticMemory instance with SQLite backend.
        """
        self._semantic_memory = memory

    def register_episodic(self, memory: EpisodicMemory) -> None:
        """Register an EpisodicMemory instance for cached replication."""
        self._episodic_memory = memory

    def register_context(self, manager: ContextWindowManager) -> None:
        """Register a ContextWindowManager for pub/sub replication.

        Context updates will be broadcast to all subscribed instances
        via Redis pub/sub, enabling multi-instance context sync.

        Args:
            manager: A ContextWindowManager instance.
        """
        self._context_manager = manager
        self.cache.subscribe(self._on_context_update)

    # ------------------------------------------------------------------
    # Semantic memory read-through caching
    # ------------------------------------------------------------------

    async def semantic_get(
        self, entry_id: str
    ) -> dict[str, Any] | None:
        """Read a semantic entry from cache first, then backend."""
        cache_key = f"semantic:{entry_id}"

        # L1: Redis cache
        cached = await self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Semantic L1 hit: {entry_id}")
            return cached

        # L2: SQLite backend
        if self._semantic_memory:
            try:
                entry = self._semantic_memory.get(entry_id)
                if entry:
                    data = self._entry_to_dict(entry)
                    await self.cache.set(cache_key, data)
                    logger.debug(f"Semantic L2 hit: {entry_id}")
                    return data
            except Exception as e:
                logger.warning(f"Semantic backend read failed: {e}")

        return None

    async def semantic_add(
        self,
        subject: str,
        predicate: str,
        object: str | None = None,
        confidence: float = 1.0,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Add a semantic entry with write-through caching."""
        if not self._semantic_memory:
            return None

        try:
            entry = self._semantic_memory.add(
                subject=subject,
                predicate=predicate,
                object=object,
                confidence=confidence,
                **kwargs,
            )
            data = self._entry_to_dict(entry)
            cache_key = f"semantic:{entry.id}"

            if self.config.strategy == ReplicationStrategy.WRITE_THROUGH:
                await self.cache.set(cache_key, data)

            # Broadcast via pub/sub
            await self.cache.publish_update({
                "type": "semantic_add",
                "entry": data,
            })

            return data
        except Exception as e:
            logger.warning(f"Semantic add failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Episodic memory read-through caching
    # ------------------------------------------------------------------

    async def episodic_get(self, entry_id: str) -> dict[str, Any] | None:
        """Read an episodic entry from cache first, then backend."""
        cache_key = f"episodic:{entry_id}"

        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        if self._episodic_memory:
            try:
                entry = self._episodic_memory.get(entry_id)
                if entry:
                    data = self._entry_to_dict(entry)
                    await self.cache.set(cache_key, data)
                    return data
            except Exception as e:
                logger.warning(f"Episodic backend read failed: {e}")

        return None

    async def episodic_add(
        self,
        content: str,
        importance: float = 0.5,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Add an episodic entry with write-through caching."""
        if not self._episodic_memory:
            return None

        try:
            entry = self._episodic_memory.add(
                content=content,
                importance=importance,
                **kwargs,
            )
            data = self._entry_to_dict(entry)
            cache_key = f"episodic:{entry.id}"

            if self.config.strategy == ReplicationStrategy.WRITE_THROUGH:
                await self.cache.set(cache_key, data)

            await self.cache.publish_update({
                "type": "episodic_add",
                "entry": data,
            })

            return data
        except Exception as e:
            logger.warning(f"Episodic add failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Context manager pub/sub
    # ------------------------------------------------------------------

    async def _on_context_update(self, update: dict[str, Any]) -> None:
        """Handle incoming context update from Redis pub/sub."""
        update_type = update.get("type", "")
        if update_type == "context_update":
            # Apply remote context update to local manager
            if self._context_manager and update.get("session_id"):
                session_id = update.get("session_id")
                # The update data contains the new message or state
                logger.debug(f"Applying context update for session {session_id}")
                # Apply diff to context manager as appropriate
                # (的具体逻辑取决于 update payload 的结构)

    async def broadcast_context_update(
        self,
        session_id: str,
        message_data: dict[str, Any],
    ) -> bool:
        """Broadcast a context update to all subscribed instances.

        Args:
            session_id: The session this update belongs to
            message_data: The message or state to broadcast

        Returns:
            True if broadcast succeeded
        """
        return await self.cache.publish_update({
            "type": "context_update",
            "session_id": session_id,
            "data": message_data,
        })

    async def broadcast_pruning_event(
        self,
        session_id: str,
        pruned_count: int,
        reason: str,
    ) -> bool:
        """Broadcast a pruning event to all subscribed instances."""
        return await self.cache.publish_update({
            "type": "pruning_event",
            "session_id": session_id,
            "pruned_count": pruned_count,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ------------------------------------------------------------------
    # Flush callback (write-back strategy → backend)
    # ------------------------------------------------------------------

    async def _on_flush_to_backend(
        self,
        key: str,
        value: dict[str, Any],
    ) -> None:
        """Flush a write-back cache entry to the appropriate backend."""
        try:
            if key.startswith(f"{self.config.key_prefix}semantic:"):
                entry_id = key.replace(f"{self.config.key_prefix}semantic:", "")
                if self._semantic_memory:
                    self._semantic_memory.update_from_cache(entry_id, value)
            elif key.startswith(f"{self.config.key_prefix}episodic:"):
                entry_id = key.replace(f"{self.config.key_prefix}episodic:", "")
                if self._episodic_memory:
                    self._episodic_memory.update_from_cache(entry_id, value)
        except Exception as e:
            logger.warning(f"Backend flush failed for {key}: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _entry_to_dict(entry: Any) -> dict[str, Any]:
        """Serialize any memory entry to a dict."""
        if hasattr(entry, "to_dict"):
            return entry.to_dict()
        # Fallback: dataclass.asdict
        import dataclasses

        if dataclasses.is_dataclass(entry):
            return dataclasses.asdict(entry)
        return dict(entry)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Return health status of all registered backends and cache.

        Returns:
            Dict with cache, semantic, episodic, and context manager status.
        """
        cache_stats = await self.cache.stats()
        return {
            "cache": cache_stats,
            "semantic_registered": self._semantic_memory is not None,
            "episodic_registered": self._episodic_memory is not None,
            "context_registered": self._context_manager is not None,
        }
