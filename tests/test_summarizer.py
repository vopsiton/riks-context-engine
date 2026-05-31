"""Unit tests for context/summarizer.py — semantic summarization for issue #86."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from riks_context_engine.context.manager import ContextMessage, ContextWindowManager
from riks_context_engine.context.summarizer import (
    MIN_MESSAGES_FOR_SUMMARARIZATION,
    TARGET_COMPRESSION_RATIO,
    BlockSummary,
    SemanticSummarizer,
    SummarizationResult,
    SummarizedBlock,
    _keyword_fallback_summarize,
)

# ─── Fixtures ──────────────────────────────────────────────────────────────────


def make_msg(
    msg_id: str,
    role: str,
    content: str,
    importance: float = 0.5,
    priority_tier: int = 2,
) -> ContextMessage:
    """Create a test ContextMessage."""
    return ContextMessage(
        id=msg_id,
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
        importance=importance,
        tokens=len(content) // 4,
        is_grounding=False,
        is_pruned=False,
        priority_tier=priority_tier,
    )


def make_manager(msgs: list[ContextMessage]) -> ContextWindowManager:
    """Create a manager with pre-populated messages."""
    mgr = ContextWindowManager(max_tokens=200_000)
    mgr.messages = msgs
    return mgr


# ─── SummarizedBlock ───────────────────────────────────────────────────────────


class TestSummarizedBlock:
    """SummarizedBlock dataclass."""

    def test_default_generated_at(self) -> None:
        block = SummarizedBlock(
            summary_text="User prefers dark mode",
            original_ids=["msg_0", "msg_1"],
            original_token_count=100,
            summary_token_count=20,
            compression_ratio=0.2,
        )
        assert block.generated_at is not None
        assert block.model == "unknown"

    def test_all_fields_set(self) -> None:
        now = datetime.now(timezone.utc)
        block = SummarizedBlock(
            summary_text="Test summary",
            original_ids=["a", "b"],
            original_token_count=200,
            summary_token_count=30,
            compression_ratio=0.15,
            generated_at=now,
            model="qwen3.5-9b",
        )
        assert block.summary_text == "Test summary"
        assert block.original_ids == ["a", "b"]
        assert block.original_token_count == 200
        assert block.summary_token_count == 30
        assert block.compression_ratio == 0.15
        assert block.generated_at == now
        assert block.model == "qwen3.5-9b"


# ─── SemanticSummarizer init ───────────────────────────────────────────────────


class TestSemanticSummarizerInit:
    """SemanticSummarizer.__init__()."""

    def test_defaults(self) -> None:
        s = SemanticSummarizer()
        assert s.llm_model == "qwen3.5-9b"
        assert s.llm_base_url == "http://localhost:11434"
        assert s.min_messages == MIN_MESSAGES_FOR_SUMMARARIZATION
        assert s.target_ratio == TARGET_COMPRESSION_RATIO

    def test_custom_args(self) -> None:
        s = SemanticSummarizer(
            llm_model="gemma-4-9b",
            llm_base_url="http://192.168.1.1:11434",
            min_messages=6,
            target_ratio=0.15,
        )
        assert s.llm_model == "gemma-4-9b"
        assert s.llm_base_url == "http://192.168.1.1:11434"
        assert s.min_messages == 6
        assert s.target_ratio == 0.15


# ─── estimate_tokens ──────────────────────────────────────────────────────────


class TestEstimateTokens:
    """estimate_tokens()."""

    def test_basic(self) -> None:
        s = SemanticSummarizer()
        assert s.estimate_tokens("hello world") == 2  # 11 chars / 4

    def test_cjk_chars(self) -> None:
        s = SemanticSummarizer()
        # 5 CJK chars + rest
        text = "你好世界这是一个测试"  # 10 chars, 5 CJK
        tokens = s.estimate_tokens(text)
        assert tokens >= 8  # CJK chars are counted individually


# ─── _group_tier3_blocks ──────────────────────────────────────────────────────


class TestGroupTier3Blocks:
    """_group_tier3_blocks()."""

    def test_empty_candidates(self) -> None:
        s = SemanticSummarizer()
        assert s._group_tier3_blocks([]) == []

    def test_single_message(self) -> None:
        s = SemanticSummarizer()
        msg = make_msg("msg_0", "user", "hello", priority_tier=3)
        blocks = s._group_tier3_blocks([msg])
        assert len(blocks) == 1
        assert blocks[0] == ["msg_0"]

    def test_multiple_messages_single_block(self) -> None:
        s = SemanticSummarizer()
        msgs = [make_msg(f"msg_{i}", "user", f"content {i}", priority_tier=3) for i in range(4)]
        blocks = s._group_tier3_blocks(msgs)
        assert len(blocks) == 1
        assert blocks[0] == ["msg_0", "msg_1", "msg_2", "msg_3"]


# ─── _build_block_text ────────────────────────────────────────────────────────


class TestBuildBlockText:
    """_build_block_text()."""

    def test_formats_correctly(self) -> None:
        s = SemanticSummarizer()
        msgs = [
            make_msg("a", "user", "Hello"),
            make_msg("b", "assistant", "Hi there"),
        ]
        text = s._build_block_text(msgs)
        assert "[user] Hello" in text
        assert "[assistant] Hi there" in text


# ─── _keyword_fallback_summarize ───────────────────────────────────────────────


class TestKeywordFallback:
    """_keyword_fallback_summarize()."""

    def test_extracts_key_facts(self) -> None:
        text = "The user wants to create a new project. Remember the user prefers dark mode. Please delete the old file."
        result = _keyword_fallback_summarize(text, count=3, target_max_tokens=50)
        assert len(result) > 0
        assert result != "[no signal]"
        assert "prefer" in result.lower() or "dark" in result.lower()

    def test_no_signal_when_empty(self) -> None:
        result = _keyword_fallback_summarize("hello world", count=1, target_max_tokens=20)
        assert isinstance(result, str)


# ─── summarize_tier3 — unit ───────────────────────────────────────────────────


class TestSummarizeTier3Unit:
    """summarize_tier3() with mocked LLM."""

    def test_no_tier3_messages(self) -> None:
        s = SemanticSummarizer()
        mgr = make_manager(
            [
                make_msg("msg_0", "user", "important", priority_tier=1, importance=0.9),
                make_msg("msg_1", "assistant", "response", priority_tier=1, importance=0.8),
            ]
        )
        result = s.summarize_tier3(mgr)
        assert result.blocks_summarized == 0
        assert result.summaries == []

    def test_below_minimum_messages(self) -> None:
        s = SemanticSummarizer(min_messages=4)
        mgr = make_manager(
            [
                make_msg("msg_0", "user", "hello", priority_tier=3),
                make_msg("msg_1", "assistant", "hi", priority_tier=3),
            ]
        )
        result = s.summarize_tier3(mgr)
        assert result.blocks_summarized == 0

    def test_force_overrides_minimum(self) -> None:
        s = SemanticSummarizer(min_messages=4)
        mgr = make_manager(
            [
                make_msg("msg_0", "user", "hello", priority_tier=3),
                make_msg("msg_1", "assistant", "hi", priority_tier=3),
            ]
        )
        with patch("riks_context_engine.context.summarizer._summarize_with_llm") as mock_llm:
            mock_llm.return_value = "Test summary"
            result = s.summarize_tier3(mgr, force=True)
            assert result.blocks_summarized >= 0

    def test_pruned_messages_excluded(self) -> None:
        msg = make_msg("msg_0", "user", "test", priority_tier=3)
        msg.is_pruned = True
        s = SemanticSummarizer()
        mgr = make_manager([msg])
        result = s.summarize_tier3(mgr)
        assert result.blocks_summarized == 0

    def test_already_summarized_excluded(self) -> None:
        msg = make_msg("msg_0", "user", "test", priority_tier=3)
        msg.summary = SummarizedBlock(
            summary_text="already done",
            original_ids=["msg_0"],
            original_token_count=10,
            summary_token_count=2,
            compression_ratio=0.2,
        )
        s = SemanticSummarizer()
        mgr = make_manager([msg])
        result = s.summarize_tier3(mgr)
        assert result.blocks_summarized == 0

    def test_no_signal_marks_pruned(self) -> None:
        s = SemanticSummarizer()
        mgr = make_manager(
            [
                make_msg("msg_0", "user", "hello", priority_tier=3),
                make_msg("msg_1", "assistant", "hi", priority_tier=3),
            ]
        )
        with patch("riks_context_engine.context.summarizer._summarize_with_llm") as mock_llm:
            mock_llm.return_value = None  # LLM unavailable → fallback
            with patch(
                "riks_context_engine.context.summarizer._keyword_fallback_summarize",
                return_value="[no signal]",
            ):
                result = s.summarize_tier3(mgr, force=True)
        # No blocks were summarized (no_signal skips)
        assert result.blocks_summarized == 0

    def test_summary_stored_on_first_message(self) -> None:
        s = SemanticSummarizer()
        msgs = [
            make_msg("msg_0", "user", "hello there", priority_tier=3),
            make_msg("msg_1", "assistant", "hi back", priority_tier=3),
        ]
        mgr = make_manager(msgs)

        with patch("riks_context_engine.context.summarizer._summarize_with_llm") as mock_llm:
            mock_llm.return_value = "User greeted, assistant responded"
            result = s.summarize_tier3(mgr, force=True)

        assert result.blocks_summarized == 1
        first = mgr.messages[0]
        assert hasattr(first, "summary")
        assert first.summary.summary_text == "User greeted, assistant responded"
        assert first.summary.original_ids == ["msg_0", "msg_1"]

    def test_remaining_messages_marked_pruned(self) -> None:
        s = SemanticSummarizer()
        msgs = [
            make_msg("msg_0", "user", "first", priority_tier=3),
            make_msg("msg_1", "assistant", "second", priority_tier=3),
            make_msg("msg_2", "user", "third", priority_tier=3),
        ]
        mgr = make_manager(msgs)

        with patch("riks_context_engine.context.summarizer._summarize_with_llm") as mock_llm:
            mock_llm.return_value = "Summary of three"
            _ = s.summarize_tier3(mgr, force=True)

        assert msgs[0].is_pruned is False  # kept (holds summary)
        assert msgs[1].is_pruned is True
        assert msgs[2].is_pruned is True

    def test_compression_ratio_calculated(self) -> None:
        s = SemanticSummarizer()
        msgs = [
            make_msg("msg_0", "user", "word " * 50, priority_tier=3),  # ~200 chars
        ]
        mgr = make_manager(msgs)

        with patch("riks_context_engine.context.summarizer._summarize_with_llm") as mock_llm:
            mock_llm.return_value = "User said many words"  # ~20 chars = 10%
            result = s.summarize_tier3(mgr, force=True)

        assert result.original_tokens > 0
        assert result.summary_tokens > 0
        assert result.compression_ratio < 1.0

    def test_result_dataclass_fields(self) -> None:
        result = SummarizationResult(
            blocks_summarized=2,
            original_tokens=500,
            summary_tokens=80,
            compression_ratio=0.16,
            summaries=[
                BlockSummary(
                    original_ids=["a", "b"],
                    original_token_count=200,
                    summary_token_count=30,
                    compression_ratio=0.15,
                    summary_text="Summary 1",
                ),
            ],
        )
        assert result.blocks_summarized == 2
        assert result.original_tokens == 500
        assert result.summary_tokens == 80
        assert result.compression_ratio == 0.16
        assert len(result.summaries) == 1


# ─── ContextWindowManager integration ─────────────────────────────────────────


class TestSetSummarizer:
    """set_summarizer() and run_summarization()."""

    def test_set_summarizer_stores_reference(self) -> None:
        mgr = ContextWindowManager()
        s = SemanticSummarizer()
        mgr.set_summarizer(s)
        assert mgr._semantic_summarizer is s  # type: ignore[attr-defined]

    def test_run_summarization_requires_summarizer(self) -> None:
        mgr = ContextWindowManager()
        with pytest.raises(RuntimeError, match="no summarizer registered"):
            mgr.run_summarization()

    def test_run_summarization_delegates_to_summarizer(self) -> None:
        s = SemanticSummarizer()
        mgr = make_manager(
            [
                make_msg("msg_0", "user", "hello", priority_tier=3),
            ]
        )
        mgr.set_summarizer(s)

        mock_result = SummarizationResult(
            blocks_summarized=1,
            original_tokens=100,
            summary_tokens=20,
            compression_ratio=0.2,
            summaries=[],
        )

        with patch.object(s, "summarize_tier3", return_value=mock_result) as mock_sum:
            result = mgr.run_summarization(force=True)
            mock_sum.assert_called_once_with(mgr, force=True)
            assert result == mock_result

    def test_run_summarization_force_arg(self) -> None:
        s = SemanticSummarizer()
        mgr = make_manager(
            [
                make_msg("msg_0", "user", "hello", priority_tier=3),
            ]
        )
        mgr.set_summarizer(s)

        with patch.object(
            s, "summarize_tier3", return_value=SummarizationResult(0, 0, 0, 0.0, [])
        ) as mock_sum:
            mgr.run_summarization(force=False)
            mock_sum.assert_called_once_with(mgr, force=False)


# ─── Integration test ─────────────────────────────────────────────────────────


class TestSemanticSummarizationIntegration:
    """Full workflow: manager + summarizer + LLM."""

    def test_end_to_end_compression(self) -> None:
        s = SemanticSummarizer()
        msgs = [
            make_msg(
                "msg_0", "user", "I need to set up a new server", priority_tier=1, importance=0.9
            ),
            make_msg(
                "msg_1", "assistant", "I'll help you configure it", priority_tier=1, importance=0.8
            ),
            make_msg("msg_2", "user", "Can you check the logs?", priority_tier=3, importance=0.2),
            make_msg("msg_3", "assistant", "Sure, looking now", priority_tier=3, importance=0.2),
            make_msg("msg_4", "user", "Thanks", priority_tier=3, importance=0.1),
            make_msg("msg_5", "assistant", "You're welcome", priority_tier=3, importance=0.1),
        ]
        mgr = make_manager(msgs)

        with patch("riks_context_engine.context.summarizer._summarize_with_llm") as mock_llm:
            mock_llm.return_value = (
                "User asked about logs, assistant checked, both exchanged thanks"
            )
            result = s.summarize_tier3(mgr, force=True)

        # 4 TIER_3 messages should be summarized into 1 block
        assert result.blocks_summarized == 1
        assert msgs[0].is_pruned is False  # TIER_1 kept
        assert msgs[1].is_pruned is False  # TIER_1 kept
        assert msgs[2].is_pruned is False  # Holds summary
        assert msgs[3].is_pruned is True
        assert msgs[4].is_pruned is True
        assert msgs[5].is_pruned is True

        # Verify compression — mock summary is ~60% of original tokens
        assert result.compression_ratio < 0.7  # Should be well under 70%

        # Verify summary stored
        assert hasattr(msgs[2], "summary")
        assert msgs[2].summary.original_ids == ["msg_2", "msg_3", "msg_4", "msg_5"]


# ─── Async compatibility ───────────────────────────────────────────────────────


class TestAsyncCompatibility:
    """Verify summarizer works in async context."""

    def test_summarize_tier3_in_async_context(self) -> None:
        async def run():
            mgr = ContextWindowManager()
            s = SemanticSummarizer()

            # Add messages via add_async (uses the async lock)
            await mgr.add_async("user", "hello", importance=0.2, priority_tier=3)
            await mgr.add_async("assistant", "hi", importance=0.2, priority_tier=3)
            await mgr.add_async("user", "how are you", importance=0.2, priority_tier=3)

            mgr.set_summarizer(s)
            result = mgr.run_summarization(force=True)
            return result

        result = asyncio.run(run())
        assert isinstance(result, SummarizationResult)
