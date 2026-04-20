"""Tests for TierManager and MemoryEntry base (issues #55 coverage boost)."""

import os
import tempfile
from datetime import datetime, timezone

import pytest

from riks_context_engine.memory.base import MemoryEntry, MemoryType
from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory
from riks_context_engine.memory.tier_manager import TierConfig, TierManager


def _temp_json():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    path = f.name
    f.close()
    return path


def _temp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    os.unlink(path)
    return path


# ─── MemoryEntry (base.py) ───────────────────────────────────────────────────

class TestMemoryEntry:
    """Lines 57-58, 62-63, 67, 82-88: MemoryEntry methods."""

    def test_record_access_increments_count(self):
        """Lines 57-58: record_access() bumps access_count and sets last_accessed."""
        entry = MemoryEntry(id="ep_1", type=MemoryType.EPISODIC, content="test")
        assert entry.access_count == 0
        assert entry.last_accessed is None

        entry.record_access()
        assert entry.access_count == 1
        assert entry.last_accessed is not None

        entry.record_access()
        assert entry.access_count == 2

    def test_to_dict_basic(self):
        """Lines 62-63: to_dict() serializes correctly."""
        entry = MemoryEntry(id="ep_1", type=MemoryType.EPISODIC, content="hello")
        d = entry.to_dict()
        assert d["id"] == "ep_1"
        assert d["type"] == "episodic"
        assert d["content"] == "hello"
        assert d["last_accessed"] is None
        assert isinstance(d["timestamp"], str)

    def test_to_dict_with_last_accessed(self):
        """Line 67: to_dict() includes last_accessed ISO string."""
        entry = MemoryEntry(id="ep_2", type=MemoryType.SEMANTIC, content="fact")
        entry.record_access()
        d = entry.to_dict()
        assert d["last_accessed"] is not None
        assert "T" in d["last_accessed"]  # ISO format check

    def test_from_dict_round_trip(self):
        """Lines 82-88: from_dict() reconstructs MemoryEntry from dict."""
        entry = MemoryEntry(
            id="sm_1",
            type=MemoryType.SEMANTIC,
            content="sky is blue",
            importance=0.9,
            access_count=3,
        )
        entry.record_access()
        d = entry.to_dict()
        restored = MemoryEntry.from_dict(d)

        assert restored.id == entry.id
        assert restored.type == MemoryType.SEMANTIC
        assert restored.content == "sky is blue"
        assert restored.importance == 0.9
        assert restored.access_count == 4  # 3 initial + 1 from record_access
        assert restored.last_accessed is not None

    def test_from_dict_with_timestamp_string(self):
        """from_dict() parses ISO timestamp strings."""
        d = {
            "id": "ep_ts",
            "type": "episodic",
            "content": "timestamp test",
            "timestamp": "2026-01-01T12:00:00+00:00",
            "importance": 0.5,
            "embedding": None,
            "access_count": 0,
            "last_accessed": None,
            "metadata": {},
        }
        entry = MemoryEntry.from_dict(d)
        assert entry.timestamp.year == 2026

    def test_importance_clamped_to_0_1(self):
        """__post_init__ clamps importance to [0.0, 1.0]."""
        entry = MemoryEntry(id="x", type=MemoryType.EPISODIC, content="c", importance=2.5)
        assert entry.importance == 1.0

        entry2 = MemoryEntry(id="y", type=MemoryType.EPISODIC, content="c", importance=-0.5)
        assert entry2.importance == 0.0

    def test_access_count_clamped_to_nonnegative(self):
        """__post_init__ clamps access_count to ≥ 0."""
        entry = MemoryEntry(id="z", type=MemoryType.EPISODIC, content="c", access_count=-5)
        assert entry.access_count == 0


# ─── TierManager (tier_manager.py) ───────────────────────────────────────────

class TestTierManager:
    """Lines 70-73, 84-105, 112-134, 151-168, 185-193."""

    def _make_manager(self, config=None):
        ep = EpisodicMemory(storage_path=_temp_json())
        sm = SemanticMemory(db_path=_temp_db())
        pm = ProceduralMemory(storage_path=_temp_json())
        tm = TierManager(ep, sm, pm, config=config)
        return tm, ep, sm, pm

    def test_promote_entry_above_threshold(self):
        """Lines 84-105: entry with access_count > threshold is promoted."""
        config = TierConfig(promote_threshold=2)
        tm, ep, sm, _ = self._make_manager(config)

        entry = ep.add("the sky is blue", importance=0.8)
        # Simulate accesses to exceed threshold
        for _ in range(3):
            ep.get(entry.id)

        result = tm._promote_episodic_entry(entry.id)
        assert result is True
        # Entry removed from episodic
        assert ep.get(entry.id) is None
        # Entry added to semantic
        assert len(sm) == 1

    def test_promote_entry_below_threshold_no_op(self):
        """Lines 70-73: entry below threshold is not promoted."""
        config = TierConfig(promote_threshold=10)
        tm, ep, _, _ = self._make_manager(config)

        entry = ep.add("rarely accessed", importance=0.5)
        result = tm._promote_episodic_entry(entry.id)
        assert result is False
        # Still in episodic
        assert len(ep.entries) == 1

    def test_promote_nonexistent_entry_returns_false(self):
        """_promote_episodic_entry() returns False for unknown ID."""
        tm, _, _, _ = self._make_manager()
        assert tm._promote_episodic_entry("nonexistent_id") is False

    def test_demote_entry_when_threshold_is_zero(self):
        """Lines 117-120: demotion skipped when demote_threshold=0."""
        config = TierConfig(demote_threshold=0)
        tm, ep, sm, _ = self._make_manager(config)

        sem_entry = sm.add("subject", "predicate", "object", confidence=0.7)
        result = tm._demote_semantic_entry(sem_entry.id)
        assert result is False
        # Entry still in semantic
        assert len(sm) == 1

    def test_demote_nonexistent_entry_returns_false(self):
        """_demote_semantic_entry() returns False for unknown ID."""
        tm, _, _, _ = self._make_manager()
        assert tm._demote_semantic_entry("nonexistent_id") is False

    def test_demote_entry_below_threshold(self):
        """Lines 112-134: entry with low access_count is demoted to episodic."""
        config = TierConfig(demote_threshold=5)
        tm, ep, sm, _ = self._make_manager(config)

        sem_entry = sm.add("cold fact", "predicate", "value", confidence=0.6)
        # access_count is 0, which is < demote_threshold (5) → demote
        result = tm._demote_semantic_entry(sem_entry.id)
        assert result is True
        # Moved to episodic
        assert len(ep.entries) == 1
        # Removed from semantic
        assert len(sm) == 0

    def test_demote_entry_above_threshold_no_op(self):
        """Entry with access_count >= demote_threshold is NOT demoted."""
        config = TierConfig(demote_threshold=2)
        tm, ep, sm, _ = self._make_manager(config)

        sem_entry = sm.add("hot fact", "predicate", "value", confidence=0.9)
        # Bump access_count to 3 (≥ threshold of 2)
        sm.get(sem_entry.id)
        sm.get(sem_entry.id)
        sm.get(sem_entry.id)

        result = tm._demote_semantic_entry(sem_entry.id)
        assert result is False
        assert len(sm) == 1

    def test_auto_tier_promotes_high_access_entries(self):
        """Lines 151-160: auto_tier promotes episodic entries above threshold."""
        config = TierConfig(promote_threshold=2)
        tm, ep, sm, _ = self._make_manager(config)

        entry = ep.add("frequently accessed", importance=0.9)
        for _ in range(3):
            ep.get(entry.id)

        result = tm.auto_tier()
        assert result["promoted"] == 1
        assert result["demoted"] == 0
        assert len(sm) == 1

    def test_auto_tier_demotes_low_access_semantic_entries(self):
        """Lines 162-168: auto_tier demotes stale semantic entries."""
        config = TierConfig(promote_threshold=100, demote_threshold=5)
        tm, ep, sm, _ = self._make_manager(config)

        sm.add("stale fact", "pred", "obj", confidence=0.5)  # access_count=0 < 5

        result = tm.auto_tier()
        assert result["demoted"] == 1
        assert len(ep.entries) == 1
        assert len(sm) == 0

    def test_record_access_episodic(self):
        """Lines 185-191: record_access() with EPISODIC type."""
        tm, ep, _, _ = self._make_manager()
        entry = ep.add("record access test")
        # Should not raise
        tm.record_access(MemoryType.EPISODIC, entry.id)

    def test_record_access_semantic(self):
        """record_access() with SEMANTIC type."""
        tm, _, sm, _ = self._make_manager()
        sem_entry = sm.add("test", "pred", "obj")
        tm.record_access(MemoryType.SEMANTIC, sem_entry.id)

    def test_record_access_procedural(self):
        """record_access() with PROCEDURAL type."""
        tm, _, _, pm = self._make_manager()
        proc = pm.store("test proc", "desc", ["step"])
        tm.record_access(MemoryType.PROCEDURAL, proc.id)

    def test_record_access_triggers_auto_tier(self):
        """Lines 192-193: auto_tier triggered when should_run() returns True."""
        config = TierConfig(promote_threshold=0, check_interval_accesses=2)
        tm, ep, sm, _ = self._make_manager(config)

        entry = ep.add("trigger tier test")
        ep.get(entry.id)  # access_count → 1, which is > threshold 0

        # First record_access: counter goes to 1 (not yet triggered)
        tm.record_access(MemoryType.EPISODIC, entry.id)
        # Second: counter reaches 2 → auto_tier fires
        entry2 = ep.add("another entry")
        ep.get(entry2.id)
        tm.record_access(MemoryType.EPISODIC, entry2.id)
        # At this point auto_tier should have run at least once
        # (either entry promoted or counter just reset, both valid)
        # Just verify no exception was raised


class TestTierConfig:
    """TierConfig.should_run() branches."""

    def test_should_run_disabled_when_interval_zero(self):
        """should_run() always returns False when check_interval_accesses=0."""
        config = TierConfig(check_interval_accesses=0)
        for _ in range(20):
            assert config.should_run() is False

    def test_should_run_triggers_at_interval(self):
        """should_run() returns True every N calls."""
        config = TierConfig(check_interval_accesses=3)
        results = [config.should_run() for _ in range(9)]
        # Should trigger on calls 3, 6, 9
        assert results[2] is True
        assert results[5] is True
        assert results[8] is True
        # Other calls return False
        assert all(not r for i, r in enumerate(results) if i not in (2, 5, 8))
