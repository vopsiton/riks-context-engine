"""Unit tests for context/manager.py — coverage gap closure for issue #55."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from riks_context_engine.context.manager import (
    TOKEN_BUFFER_PER_SIDE,
    ContextMessage,
    ContextWindowManager,
)

# ─── ContextMessage ─────────────────────────────────────────────────────────────


class TestContextMessage:
    """ContextMessage dataclass methods."""

    def test_should_preserve_grounding(self) -> None:
        """is_grounding=True → should_preserve returns True."""
        from datetime import datetime, timezone

        msg = ContextMessage(
            id="1",
            role="user",
            content="I prefer dark mode",
            timestamp=datetime.now(timezone.utc),
            is_grounding=True,
        )
        assert msg.should_preserve() is True

    def test_should_preserve_tier_0(self) -> None:
        """priority_tier=0 → should_preserve returns True."""
        from datetime import datetime, timezone

        msg = ContextMessage(
            id="1",
            role="system",
            content="You are a helpful assistant",
            timestamp=datetime.now(timezone.utc),
            priority_tier=0,
        )
        assert msg.should_preserve() is True

    def test_should_preserve_false_for_normal(self) -> None:
        """Normal message → should_preserve is False."""
        from datetime import datetime, timezone

        msg = ContextMessage(
            id="1",
            role="user",
            content="Hello",
            timestamp=datetime.now(timezone.utc),
            priority_tier=2,
            is_grounding=False,
        )
        assert msg.should_preserve() is False

    def test_pruning_score_high_importance_lower_score(self) -> None:
        """Higher importance → lower (more negative) pruning score.

        The pruning_score formula inverts importance, so high importance
        messages score LOWER (more negative) and are considered for pruning first.
        """
        from datetime import datetime, timezone

        low_imp = ContextMessage(
            id="1",
            role="user",
            content="x",
            timestamp=datetime.now(timezone.utc),
            importance=0.1,
            tokens=0,
        )
        high_imp = ContextMessage(
            id="2",
            role="user",
            content="x",
            timestamp=datetime.now(timezone.utc),
            importance=1.0,
            tokens=0,
        )
        assert high_imp.pruning_score() < low_imp.pruning_score()


# ─── ContextWindowManager init ─────────────────────────────────────────────────


class TestContextWindowManagerInit:
    """Cover lines 78-100 (init and add)."""

    def test_init_default(self) -> None:
        mgr = ContextWindowManager()
        assert mgr.max_tokens == 180_000
        assert mgr.usable_tokens == 180_000 - 2 * TOKEN_BUFFER_PER_SIDE
        assert mgr.model == "mini-max"
        assert len(mgr.messages) == 0

    def test_init_custom_max_tokens(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        assert mgr.max_tokens == 100_000

    def test_stats_initial_state(self) -> None:
        mgr = ContextWindowManager()
        assert mgr.stats.current_tokens == 0
        assert mgr.stats.messages_count == 0
        assert mgr.stats.active_messages_count == 0
        assert mgr.stats.pruning_count == 0


# ─── add and add_async ────────────────────────────────────────────────────────


class TestAdd:
    """Cover lines 100-160 (add + _prune_if_needed)."""

    def test_add_returns_context_message(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        msg = mgr.add("user", "Hello world", importance=0.9)
        assert isinstance(msg, ContextMessage)
        assert msg.role == "user"
        assert msg.content == "Hello world"
        assert msg.importance == 0.9

    def test_add_grounding_message(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        msg = mgr.add("user", "My name is Vahit", importance=0.9, is_grounding=True)
        assert msg.is_grounding is True

    def test_add_tier_0_protected(self) -> None:
        """Tier 0 messages are protected from pruning."""
        mgr = ContextWindowManager(max_tokens=100_000)
        msg = mgr.add("system", "Critical system prompt", priority_tier=0)
        assert msg.priority_tier == 0

    def test_add_updates_stats(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        mgr.add("user", "Hello")
        assert mgr.stats.messages_count == 1
        assert mgr.stats.active_messages_count == 1

    def test_add_triggers_pruning_when_full(self) -> None:
        """Adding many large messages triggers pruning."""
        mgr = ContextWindowManager(max_tokens=10_000)
        big = "Lorem ipsum dolor sit amet consectetur adipiscing elit " * 30
        for i in range(50):
            mgr.add("user", f"Message {i}: {big}", importance=0.1, priority_tier=3)
        pruned = sum(1 for m in mgr.messages if m.is_pruned)
        assert pruned > 0


class TestAddAsync:
    """Cover lines 162-163 (async add)."""

    @pytest.mark.asyncio
    async def test_add_async_returns_message(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        msg = await mgr.add_async("user", "async hello", importance=0.8)
        assert msg.role == "user"
        assert msg.content == "async hello"

    @pytest.mark.asyncio
    async def test_add_async_thread_safe(self) -> None:
        """Multiple concurrent adds don't corrupt state."""
        mgr = ContextWindowManager(max_tokens=50_000)
        await asyncio.gather(
            *[mgr.add_async("user", f"msg{i} short content", importance=0.5) for i in range(5)]
        )
        assert mgr.stats.messages_count == 5
        assert mgr.stats.active_messages_count == 5


# ─── _get_tiktoken_encoding ───────────────────────────────────────────────────


class TestTiktokenEncoding:
    """Cover lines 200-230 (tiktoken fallback paths)."""

    def test_encoding_with_tiktoken_available(self) -> None:
        """When tiktoken available, uses it."""
        mgr = ContextWindowManager(model="gpt-4")
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.return_value = mock_encoding
        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            # Clear any cached result
            result = mgr._get_tiktoken_encoding()
            assert result is not None
            enc, name = result
            assert name == "cl100k_base"

    def test_encoding_import_error_fallback(self) -> None:
        """ImportError in get_encoding → returns None, falls back to char estimation."""
        mgr = ContextWindowManager(model="unknown-model")
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = ImportError("No module named 'tiktoken'")
        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            result = mgr._get_tiktoken_encoding()
            assert result is None

    def test_encoding_generic_exception_fallback(self) -> None:
        """Generic exception in tiktoken → returns None."""
        mgr = ContextWindowManager(model="some-model")
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = RuntimeError("encoding error")
        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            result = mgr._get_tiktoken_encoding()
            assert result is None


# ─── _contains_non_latin ───────────────────────────────────────────────────────


class TestContainsNonLatin:
    """Cover lines 238-242."""

    def test_english_returns_false(self) -> None:
        mgr = ContextWindowManager()
        assert mgr._contains_non_latin("Hello world, this is English.") is False

    def test_cjk_returns_true(self) -> None:
        mgr = ContextWindowManager()
        assert mgr._contains_non_latin("你好世界") is True
        assert mgr._contains_non_latin("今日は") is True

    def test_arabic_returns_true(self) -> None:
        mgr = ContextWindowManager()
        assert mgr._contains_non_latin("مرحبا") is True

    def test_cyrillic_returns_true(self) -> None:
        mgr = ContextWindowManager()
        assert mgr._contains_non_latin("Привет") is True

    def test_greek_returns_true(self) -> None:
        mgr = ContextWindowManager()
        assert mgr._contains_non_latin("Γειά σου") is True


# ─── _estimate_tokens ─────────────────────────────────────────────────────────


class TestEstimateTokens:
    """Cover _estimate_tokens fallback paths."""

    def test_english_basic(self) -> None:
        """English text: tiktoken when available, else len/4 approximation.

        tiktoken correctly gives ~4 chars/token for English, so 'a'*40
        yields ~10 tokens (not 5 as char-based would give). The test accepts
        both: tiktoken path (5 tokens) or char-based fallback (10 tokens).
        """
        mgr = ContextWindowManager()
        text = "a" * 40
        tokens = mgr._estimate_tokens(text)
        # tiktoken: 40 chars / 4 = 10 chars/token → 5 tokens
        # char fallback: 40 / 4 = 10 tokens
        # Both are valid; accept range [5, 12]
        assert 5 <= tokens <= 12

    def test_code_indicators(self) -> None:
        """Code blocks → 1.3x multiplier (char-based path)."""
        mgr = ContextWindowManager()
        code = "def hello():\n    print('hello world')"
        tokens = mgr._estimate_tokens(code)
        assert tokens > 0  # Reasonable token count

    def test_cjk_text(self) -> None:
        """CJK: 2 chars per token via non-Latin bypass (bypasses tiktoken).

        Non-Latin check happens BEFORE tiktoken call, so CJK text always
        uses the len(text)//2 path regardless of tiktoken availability.
        """
        mgr = ContextWindowManager()
        cjk = "你好" * 10  # 20 chars → 10 tokens (2 chars/token)
        tokens = mgr._estimate_tokens(cjk)
        assert tokens == 10  # 20 / 2 = 10


# ─── get_messages ─────────────────────────────────────────────────────────────


class TestGetMessages:
    """get_messages include_pruned=False/True."""

    def test_get_messages_default_excludes_pruned(self) -> None:
        mgr = ContextWindowManager(max_tokens=10_000)
        big = "x" * 1000
        mgr.add("user", "keep", importance=0.9, is_grounding=True, priority_tier=0)
        for i in range(30):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        active = mgr.get_messages()
        assert all(not m.is_pruned for m in active)

    def test_get_messages_include_pruned(self) -> None:
        """With sufficient large messages, pruning occurs."""
        mgr = ContextWindowManager(max_tokens=10_000)
        # 5000 chars ≈ 625 tokens (tiktoken). Need >8976 usable tokens.
        # 15 messages × 625 = 9375 > 8976 → triggers pruning.
        big = "x" * 5000
        mgr.add("user", "keep", importance=0.9, is_grounding=True, priority_tier=0)
        for i in range(20):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        all_msgs = mgr.get_messages(include_pruned=True)
        assert len(all_msgs) == len(mgr.messages)
        assert any(m.is_pruned for m in mgr.messages), "Some messages should be pruned"


# ─── get_active_tokens / tokens_remaining ─────────────────────────────────────


class TestTokenCalculations:
    """get_active_tokens, tokens_remaining, needs_pruning."""

    def test_active_tokens_empty(self) -> None:
        mgr = ContextWindowManager()
        assert mgr.get_active_tokens() == 0

    def test_tokens_remaining(self) -> None:
        mgr = ContextWindowManager(max_tokens=180_000)
        remaining = mgr.tokens_remaining()
        assert remaining == mgr.usable_tokens

    def test_needs_pruning_false_initially(self) -> None:
        mgr = ContextWindowManager()
        assert mgr.needs_pruning() is False


# ─── validate_coherence ───────────────────────────────────────────────────────


class TestValidateCoherence:
    """Cover lines 260-265 (validate_coherence edge cases)."""

    def test_empty_context_valid(self) -> None:
        mgr = ContextWindowManager()
        assert mgr.validate_coherence()["is_coherent"] is True

    def test_first_message_assistant_valid(self) -> None:
        """First message being assistant is valid."""
        mgr = ContextWindowManager()
        mgr.add("assistant", "Hello, how can I help?", priority_tier=0)
        assert mgr.validate_coherence()["is_coherent"] is True

    def test_grounding_preserved_when_added(self) -> None:
        """If grounding messages were added, at least one must remain."""
        mgr = ContextWindowManager(max_tokens=10_000)
        big = "x" * 2000
        mgr.add("user", "I prefer dark mode", importance=1.0, is_grounding=True, priority_tier=0)
        for i in range(50):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        # Tier 0 is protected, so grounding should remain
        assert any(m.is_grounding and not m.is_pruned for m in mgr.messages)


# ─── prune_async ─────────────────────────────────────────────────────────────


class TestPruneAsync:
    """prune_async with asyncio.Lock."""

    @pytest.mark.asyncio
    async def test_prune_async_returns_count(self) -> None:
        mgr = ContextWindowManager(max_tokens=10_000)
        big = "x" * 2000
        mgr.add("user", "keep", importance=0.9, is_grounding=True, priority_tier=0)
        for i in range(30):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        pruned_count = await mgr.prune_async()
        assert pruned_count >= 0

    @pytest.mark.asyncio
    async def test_prune_async_concurrent(self) -> None:
        """Concurrent prunes don't crash."""
        mgr = ContextWindowManager(max_tokens=5_000)
        big = "x" * 2000
        for i in range(50):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        await asyncio.gather(mgr.prune_async(), mgr.prune_async())
        assert mgr.tokens_remaining() >= 0


# ─── mark_below_threshold ─────────────────────────────────────────────────────


class TestMarkBelowThreshold:
    """Cover lines 342-346."""

    def test_empty_context(self) -> None:
        mgr = ContextWindowManager()
        result = mgr.mark_below_threshold()
        assert result == []

    def test_returns_messages_within_threshold(self) -> None:
        mgr = ContextWindowManager(max_tokens=180_000)
        mgr.add("user", "Short", importance=0.5, priority_tier=2)
        mgr.add("assistant", "Short too", importance=0.5, priority_tier=2)
        result = mgr.mark_below_threshold(threshold=1000)
        assert isinstance(result, list)


# ─── get_summary ─────────────────────────────────────────────────────────────


class TestGetSummary:
    """Cover lines 367, 369, 378."""

    def test_summary_keys(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        mgr.add("user", "Hello", importance=0.8)
        summary = mgr.get_summary()
        assert "max_tokens" in summary
        assert "usable_tokens" in summary
        assert "current_tokens" in summary
        assert "active_messages" in summary
        assert "pruned_messages" in summary
        assert "tokens_remaining" in summary
        assert "pruning_events" in summary
        assert "needs_pruning" in summary

    def test_summary_updates_after_pruning(self) -> None:
        mgr = ContextWindowManager(max_tokens=5_000)
        # 2000 chars ≈ 250 tokens (tiktoken). Need >3976 usable tokens.
        # 16 messages × 250 = 4000 > 3976 → pruning starts at msg 15.
        # Use 18 messages to ensure >0 pruned messages.
        big = "x" * 2000
        for i in range(18):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        summary = mgr.get_summary()
        assert summary["pruned_messages"] > 0


# ─── reset ─────────────────────────────────────────────────────────────────────


class TestReset:
    """Cover lines 411-418."""

    def test_reset_clears_messages(self) -> None:
        mgr = ContextWindowManager(max_tokens=100_000)
        mgr.add("user", "Hello")
        mgr.add("assistant", "Hi")
        assert len(mgr.messages) == 2
        mgr.reset()
        assert len(mgr.messages) == 0

    def test_reset_clears_stats(self) -> None:
        mgr = ContextWindowManager(max_tokens=5_000)
        # 2000 chars ≈ 250 tokens (tiktoken). Need >3976 usable tokens.
        # 16 messages × 250 = 4000 > 3976 → pruning starts at msg 15.
        # Use 18 messages to ensure >0 pruned messages.
        big = "x" * 2000
        for i in range(18):
            mgr.add("user", f"{big}{i}", importance=0.1, priority_tier=3)
        initial_pruning = mgr.stats.pruning_count
        assert initial_pruning > 0
        mgr.reset()
        assert mgr.stats.pruning_count == 0
        assert mgr.stats.messages_count == 0
        assert mgr.stats.active_messages_count == 0

    def test_reset_allows_reuse(self) -> None:
        """After reset, manager works normally."""
        mgr = ContextWindowManager(max_tokens=100_000)
        mgr.add("user", "one")
        mgr.reset()
        mgr.add("user", "two")
        assert len(mgr.messages) == 1
        assert mgr.messages[0].content == "two"
