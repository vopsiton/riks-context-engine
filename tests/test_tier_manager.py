"""Test TierManager for coverage."""
import pytest

from riks_context_engine.memory.tier_manager import (
    TierManager,
    TierConfig,
    MemoryType,
)


class TestTierConfig:
    """Tests for TierConfig."""

    def test_default_config(self):
        config = TierConfig()
        assert config.promote_threshold == 5
        assert config.demote_threshold == 0
        assert config.max_episodic == 1000
        assert config.check_interval_accesses == 10

    def test_should_run_false_by_default(self):
        config = TierConfig()
        # Run 9 times, should not trigger
        for _ in range(9):
            assert config.should_run() is False
        # 10th time should trigger
        assert config.should_run() is True

    def test_should_run_disabled(self):
        config = TierConfig(check_interval_accesses=0)
        for _ in range(100):
            assert config.should_run() is False

    def test_should_run_resets_counter(self):
        config = TierConfig(check_interval_accesses=3)
        # Trigger twice
        config.should_run()  # counter=1
        config.should_run()  # counter=2
        result = config.should_run()  # counter=3 -> triggers, resets
        assert result is True
        # Counter reset
        for _ in range(2):
            assert config.should_run() is False
        result = config.should_run()  # counter=3 -> triggers again
        assert result is True


class TestTierManagerRequiresStores:
    """TierManager requires stores, test MemoryType enum."""

    def test_memory_type_enum_exists(self):
        """MemoryType enum should exist."""
        assert MemoryType.EPISODIC is not None
        assert MemoryType.SEMANTIC is not None
        assert MemoryType.PROCEDURAL is not None
