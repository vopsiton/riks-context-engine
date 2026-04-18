"""TierManager - Automatic promotion/demotion across memory tiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import MemoryType

if TYPE_CHECKING:
    from .episodic import EpisodicMemory
    from .procedural import ProceduralMemory
    from .semantic import SemanticMemory


@dataclass
class TierConfig:
    """Configuration for automatic tiering."""

    promote_threshold: int = 5
    """Access count threshold for promoting episodic → semantic."""

    demote_threshold: int = 0
    """Minimum access count before demoting semantic → episodic (0 = never demote)."""

    max_episodic: int = 1000
    """Max episodic entries before pruning."""

    check_interval_accesses: int = 10
    """Run auto_tier every N cumulative accesses (0 = disabled)."""

    _access_counter: int = field(default=0, repr=False)

    def should_run(self) -> bool:
        if self.check_interval_accesses == 0:
            return False
        self._access_counter += 1
        if self._access_counter >= self.check_interval_accesses:
            self._access_counter = 0
            return True
        return False


class TierManager:
    """Manages automatic promotion and demotion across memory tiers.

    Monitors access frequency across episodic and semantic stores and
    promotes frequently-accessed episodic entries to semantic memory,
    or demotes stale semantic entries back to episodic.

    Parameters
    ----------
    episodic : EpisodicMemory
        The episodic memory store.
    semantic : SemanticMemory
        The semantic memory store.
    procedural : ProceduralMemory
        The procedural memory store (not subject to tiering).
    config : TierConfig | None
        Tiering thresholds and behaviour.
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        procedural: ProceduralMemory,
        config: TierConfig | None = None,
    ) -> None:
        self.episodic = episodic
        self.semantic = semantic
        self.procedural = procedural
        self.config = config or TierConfig()

    # ------------------------------------------------------------------
    # Promotion / Demotion helpers
    # ------------------------------------------------------------------

    def _promote_episodic_entry(self, entry_id: str, threshold: int | None = None) -> bool:
        """Promote a frequently-accessed episodic entry to semantic memory.

        Returns True if promotion occurred.
        """
        cfg = self.config
        threshold = threshold if threshold is not None else cfg.promote_threshold

        ep_entry = self.episodic.get(entry_id)
        if ep_entry is None:
            return False

        if ep_entry.access_count <= threshold:
            return False

        # Create semantic entry from episodic
        text = ep_entry.content
        self.semantic.add(
            subject=text.split(" ")[0] if text else "unknown",
            predicate="observed_as",
            object=text,
            confidence=ep_entry.importance,
        )

        # Remove from episodic
        self.episodic.delete(entry_id)
        return True

    def _demote_semantic_entry(self, entry_id: str) -> bool:
        """Demote a semantic entry back to episodic (if access_count is low).

        Returns True if demotion occurred.
        """
        sem_entry = self.semantic.get(entry_id)
        if sem_entry is None:
            return False

        cfg = self.config
        if cfg.demote_threshold <= 0:
            return False

        if sem_entry.access_count >= cfg.demote_threshold:
            return False

        # Store in episodic
        object_text = sem_entry.object or f"{sem_entry.subject} {sem_entry.predicate}"
        self.episodic.add(
            content=object_text,
            importance=sem_entry.confidence,
            tags=[],
            embedding=None,
        )

        # Remove from semantic
        self.semantic.delete(entry_id)
        return True

    # ------------------------------------------------------------------
    # Main auto_tier entry point
    # ------------------------------------------------------------------

    def auto_tier(self) -> dict[str, int]:
        """Run one tiering cycle.

        Promotes high-access-count episodic entries to semantic,
        demotes low-access-count semantic entries back to episodic.

        Returns
        -------
        dict[str, int]
            Summary with keys ``promoted``, ``demoted``.
        """
        promoted = 0
        demoted = 0

        # Scan episodic entries for promotion candidates
        for ep_entry in list(self.episodic._entries.values()):
            if ep_entry.access_count > self.config.promote_threshold:
                if self._promote_episodic_entry(ep_entry.id):
                    promoted += 1

        # Scan semantic entries for demotion candidates
        if self.config.demote_threshold > 0:
            with self.semantic._conn() as conn:
                rows = conn.execute("SELECT id FROM semantic_entries").fetchall()
            for row in rows:
                if self._demote_semantic_entry(row["id"]):
                    demoted += 1

        return {"promoted": promoted, "demoted": demoted}

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def record_access(
        self,
        memory_type: MemoryType,
        entry_id: str,
    ) -> None:
        """Record an access on an entry and optionally trigger auto_tier.

        Call this whenever an entry is retrieved from any tier.
        """
        # Import here to avoid circular imports at module level

        if memory_type == MemoryType.EPISODIC:
            self.episodic.get(entry_id)
        elif memory_type == MemoryType.SEMANTIC:
            self.semantic.get(entry_id)
        elif memory_type == MemoryType.PROCEDURAL:
            self.procedural.get(entry_id)

        if self.config.should_run():
            self.auto_tier()
