"""Tests for context module."""

import pytest

from riks_context_engine.context.manager import ContextMessage, ContextWindowManager, ContextStats


class TestContextWindowManager:
    def test_init(self):
        mgr = ContextWindowManager(max_tokens=100_000)
        assert mgr.max_tokens == 100_000
        assert len(mgr.messages) == 0

    def test_add_message(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        msg = mgr.add(role="user", content="Hello, who are you?", importance=0.9)
        assert msg.role == "user"
        assert msg.content == "Hello, who are you?"
        assert len(mgr.messages) == 1

    def test_stats_update(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        mgr.add(role="user", content="Test")
        assert mgr.stats.messages_count == 1
        assert mgr.stats.current_tokens > 0

    def test_grounding_message_flag(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        msg = mgr.add(role="system", content="User prefers short replies", importance=0.9, is_grounding=True)
        assert msg.is_grounding is True

    def test_validate_coherence(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        assert mgr.validate_coherence() is True
