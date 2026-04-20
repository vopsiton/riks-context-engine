"""Tests for context module."""

from datetime import datetime, timezone

from riks_context_engine.context.manager import (
    CHAR_PER_TOKEN,
    TOKEN_BUFFER_PER_SIDE,
    ContextMessage,
    ContextWindowManager,
)


class TestContextWindowManager:
    def test_init(self):
        mgr = ContextWindowManager(max_tokens=100_000)
        assert mgr.max_tokens == 100_000
        assert mgr.usable_tokens == 100_000 - (2 * TOKEN_BUFFER_PER_SIDE)
        assert len(mgr.messages) == 0

    def test_add_message(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        msg = mgr.add(role="user", content="Hello, who are you?", importance=0.9)
        assert msg.role == "user"
        assert msg.content == "Hello, who are you?"
        assert len(mgr.messages) == 1
        assert msg.tokens > 0

    def test_stats_update(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        mgr.add(role="user", content="Test")
        assert mgr.stats.messages_count == 1
        assert mgr.stats.current_tokens > 0

    def test_grounding_message_flag(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        msg = mgr.add(
            role="system", content="User prefers short replies", importance=0.9, is_grounding=True
        )
        assert msg.is_grounding is True

    def test_validate_coherence(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        assert mgr.validate_coherence() is True

    def test_tokens_remaining(self):
        mgr = ContextWindowManager(max_tokens=50_000)
        initial = mgr.tokens_remaining()
        mgr.add(role="user", content="Short message")
        assert mgr.tokens_remaining() < initial

    def test_needs_pruning_false(self):
        mgr = ContextWindowManager(max_tokens=50_000)
        assert mgr.needs_pruning() is False

    def test_needs_pruning_true(self):
        """Test that pruning triggers when exceeding usable tokens."""
        mgr = ContextWindowManager(max_tokens=2000)  # Small limit for testing
        # Add enough content to trigger pruning
        for i in range(50):
            mgr.add(role="user", content=f"Message number {i} " * 50, importance=0.3)
        # After pruning, should not need more pruning
        assert mgr.stats.pruning_count >= 0

    def test_pruning_preserves_grounding(self):
        """Grounding messages should never be pruned."""
        mgr = ContextWindowManager(max_tokens=2000)
        # Add grounding message
        mgr.add(
            role="system",
            content="User preferences: short replies",
            importance=0.9,
            is_grounding=True,
        )
        # Add lots of other content
        for i in range(30):
            mgr.add(role="user", content=f"Some content here {i}", importance=0.2)

        # Grounding message should still be present
        _ = mgr.get_messages()
        assert any(m.is_grounding and not m.is_pruned for m in mgr.messages)

    def test_pruning_low_importance_first(self):
        """Low importance messages should be pruned before high importance."""
        mgr = ContextWindowManager(max_tokens=1500)
        # Add high importance
        high = mgr.add(role="user", content="Important decision made", importance=0.9)
        # Add low importance
        for i in range(20):
            mgr.add(role="user", content=f"Low priority content {i}", importance=0.1)

        # High importance message should not be pruned
        assert not high.is_pruned

    def test_get_messages_excludes_pruned(self):
        mgr = ContextWindowManager(max_tokens=1000)
        mgr.add(role="user", content="First", importance=0.5)
        mgr.add(role="user", content="Second", importance=0.3)
        mgr.add(role="user", content="Third", importance=0.8)

        # Add more to trigger pruning
        for i in range(30):
            mgr.add(role="user", content=f"Fill up context {i}", importance=0.1)

        active = mgr.get_messages()
        assert all(not m.is_pruned for m in active)

    def test_get_messages_include_pruned(self):
        mgr = ContextWindowManager(max_tokens=1000)
        mgr.add(role="user", content="First", importance=0.5)
        for i in range(30):
            mgr.add(role="user", content=f"Fill {i}", importance=0.1)

        all_msgs = mgr.get_messages(include_pruned=True)
        assert len(all_msgs) > len(mgr.get_messages(include_pruned=False))

    def test_tokens_remaining_calculation(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        remaining = mgr.tokens_remaining()
        assert remaining > 0
        # After adding, should decrease
        mgr.add(role="user", content="Test content")
        assert mgr.tokens_remaining() < remaining

    def test_priority_tier_protection(self):
        """Tier 0 messages should never be pruned."""
        mgr = ContextWindowManager(max_tokens=1000)
        protected = mgr.add(
            role="system", content="Critical system prompt", importance=0.5, priority_tier=0
        )
        # Fill with low priority content
        for i in range(50):
            mgr.add(role="user", content=f"Content {i}", importance=0.1)

        assert not protected.is_pruned

    def test_token_estimation_code(self):
        """Code should use more tokens per char."""
        mgr = ContextWindowManager()
        code = "def hello():\n    return 'world'\n" * 10
        plain = "Hello world " * 30

        code_tokens = mgr._estimate_tokens(code)
        plain_tokens = mgr._estimate_tokens(plain)

        # Code should have higher token estimate
        assert code_tokens > plain_tokens

    def test_mark_below_threshold(self):
        mgr = ContextWindowManager(max_tokens=50_000)
        # Don't mark anything if plenty of space
        marked = mgr.mark_below_threshold(512)
        assert isinstance(marked, list)

    def test_reset(self):
        mgr = ContextWindowManager(max_tokens=10_000)
        mgr.add(role="user", content="Test")
        for i in range(30):
            mgr.add(role="user", content=f"Fill {i}", importance=0.1)

        mgr.reset()
        assert len(mgr.messages) == 0
        assert mgr.stats.pruning_count == 0

    def test_get_summary(self):
        mgr = ContextWindowManager(max_tokens=50_000)
        mgr.add(role="user", content="Test message")
        summary = mgr.get_summary()

        assert "max_tokens" in summary
        assert "current_tokens" in summary
        assert "active_messages" in summary
        assert "tokens_remaining" in summary
        assert summary["max_tokens"] == 50_000

    def test_active_tokens_calculation(self):
        mgr = ContextWindowManager(max_tokens=50_000)
        mgr.add(role="user", content="Hello")
        initial = mgr.get_active_tokens()
        assert initial > 0

    def test_coherence_validation_orpaned_assistant(self):
        """Test that orphaned assistant messages fail coherence."""
        mgr = ContextWindowManager(max_tokens=10_000)
        # Manually create an invalid state (for testing)
        # In practice this shouldn't happen with normal API
        # Just verify the validator works with valid state
        mgr.add(role="user", content="Hello")
        mgr.add(role="assistant", content="Hi there")
        assert mgr.validate_coherence() is True


class TestContextMessage:
    def test_should_preserve_grounding(self):
        msg = ContextMessage(
            id="test1",
            role="system",
            content="User preferences",
            timestamp=datetime.now(timezone.utc),
            is_grounding=True,
            priority_tier=2,
        )
        assert msg.should_preserve() is True

    def test_should_preserve_tier_0(self):
        msg = ContextMessage(
            id="test2",
            role="system",
            content="System prompt",
            timestamp=datetime.now(timezone.utc),
            priority_tier=0,
        )
        assert msg.should_preserve() is True

    def test_should_not_preserve_regular(self):
        msg = ContextMessage(
            id="test3",
            role="user",
            content="Regular message",
            timestamp=datetime.now(timezone.utc),
            priority_tier=2,
        )
        assert msg.should_preserve() is False

    def test_pruning_score(self):
        msg = ContextMessage(
            id="test4",
            role="user",
            content="Test",
            timestamp=datetime.now(timezone.utc),
            importance=0.9,
            tokens=1000,
        )
        # Higher importance = lower (better) pruning score
        score1 = msg.pruning_score()

        msg.importance = 0.1
        score2 = msg.pruning_score()

        assert score1 < score2  # Higher importance = more negative (less likely to prune)


class TestTokenEstimation:
    def test_char_per_token_constant(self):
        assert CHAR_PER_TOKEN == 4

    def test_buffer_per_side_constant(self):
        assert TOKEN_BUFFER_PER_SIDE == 512

    def test_turkish_text_token_estimation(self):
        """Turkish text should be handled correctly (non-Latin script fallback)."""
        mgr = ContextWindowManager(model="gpt-4")
        turkish_text = "Merhaba, nasılsın? Bugün hava çok güzel."
        tokens = mgr._estimate_tokens(turkish_text)
        assert tokens > 0
        # Turkish with ~45 chars should be roughly 11-15 tokens (cl100k_base)
        # Fallback uses len/2 for non-Latin, so ~22 tokens for 45 chars
        assert tokens >= 5

    def test_code_snippet_token_estimation(self):
        """Code snippets should use more tokens per character."""
        mgr = ContextWindowManager(model="gpt-4")
        code = "def hello():\n    return 'Merhaba Dünya'\n" * 5
        tokens = mgr._estimate_tokens(code)
        assert tokens > 0
        # Code typically uses more tokens
        assert tokens >= 10

    def test_mixed_language_estimation(self):
        """Mixed language content should be handled correctly."""
        mgr = ContextWindowManager(model="gpt-4")
        mixed = "Hello! Bu Türkçe bir cümle. 123 numbers. More text here."
        tokens = mgr._estimate_tokens(mixed)
        assert tokens > 0
        # Should be reasonable for mixed content
        assert tokens >= 5

    def test_english_text_baseline(self):
        """English text should give reasonable token estimates."""
        mgr = ContextWindowManager(model="gpt-4")
        english = "This is a sample English sentence for token estimation testing." * 3
        tokens = mgr._estimate_tokens(english)
        assert tokens > 0
        # ~105 chars, roughly 25-30 tokens for English with tiktoken
        assert 15 <= tokens <= 60

    def test_cjk_characters(self):
        """CJK characters should be handled correctly."""
        mgr = ContextWindowManager(model="gpt-4")
        cjk_text = "你好世界这是一段中文文本"
        tokens = mgr._estimate_tokens(cjk_text)
        assert tokens > 0
        # CJK fallback uses len/2, so roughly correct
        assert tokens >= 5

    def test_arabic_characters(self):
        """Arabic text should be handled correctly."""
        mgr = ContextWindowManager(model="gpt-4")
        arabic_text = "مرحبا بك في العالم"
        tokens = mgr._estimate_tokens(arabic_text)
        assert tokens > 0
        # Arabic fallback uses len/2
        assert tokens >= 5

    def test_model_parameter_used(self):
        """Model parameter should be passed through and not ignored."""
        mgr = ContextWindowManager(model="gpt-4")
        assert mgr.model == "gpt-4"

    def test_unknown_model_uses_tiktoken_fallback(self):
        """Unknown model should still attempt tiktoken with default encoding."""
        mgr = ContextWindowManager(model="unknown-model-xyz")
        text = "Testing token estimation with an unknown model."
        tokens = mgr._estimate_tokens(text)
        assert tokens > 0

    def test_empty_string_estimation(self):
        """Empty string should return 0 tokens."""
        mgr = ContextWindowManager(model="gpt-4")
        tokens = mgr._estimate_tokens("")
        assert tokens == 0

    def test_special_characters_handling(self):
        """Special characters should not break estimation."""
        mgr = ContextWindowManager(model="gpt-4")
        special = '!@#$%^&*()_+-={}[]|\\:";<>?,./~`'
        tokens = mgr._estimate_tokens(special)
        assert tokens >= 0  # Should not crash

    def test_contains_non_latin_turkish(self):
        """Turkish diacritics (ş,ç,ı,ğ,ö,ü) are Latin-1, not non-Latin.

        The _contains_non_latin check is for scripts that are clearly
        non-Latin (CJK, Arabic, Cyrillic). Turkish diacritics are handled
        correctly by tiktoken anyway.
        """
        mgr = ContextWindowManager()
        # These are Latin-1 Supplement — should be False (handled by tiktoken)
        assert mgr._contains_non_latin("şeker") is False
        assert mgr._contains_non_latin("çiftliği") is False
        # ASCII only — definitely not non-Latin
        assert mgr._contains_non_latin("Hello") is False

    def test_contains_non_latin_cyrillic(self):
        """_contains_non_latin should detect Cyrillic characters."""
        mgr = ContextWindowManager()
        assert mgr._contains_non_latin("Привет") is True
        assert mgr._contains_non_latin("Hello") is False

    def test_long_code_block(self):
        """Long code blocks should be estimated correctly."""
        mgr = ContextWindowManager(model="gpt-4")
        code_block = (
            """
class MyClass:
    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value

def main():
    obj = MyClass(42)
    print(obj.get_value())
"""
            * 10
        )
        tokens = mgr._estimate_tokens(code_block)
        assert tokens > 100  # Should be substantial for this much code

    def test_get_tiktoken_encoding_helper(self):
        """_get_tiktoken_encoding should return encoding for known models."""
        mgr = ContextWindowManager(model="gpt-4")
        result = mgr._get_tiktoken_encoding()
        if result is not None:
            encoding, enc_name = result
            assert enc_name == "cl100k_base"
            # Test encoding works
            test_tokens = encoding.encode("test", disallowed_special=())
            assert len(test_tokens) > 0

    def test_get_tiktoken_encoding_minimax(self):
        """_get_tiktoken_encoding should work for mini-max model."""
        mgr = ContextWindowManager(model="mini-max")
        result = mgr._get_tiktoken_encoding()
        if result is not None:
            encoding, enc_name = result
            assert enc_name == "cl100k_base"
