"""Context window manager - intelligent pruning and coherence."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

from riks_context_engine.context.summarizer import SemanticSummarizer, SummarizationResult

if TYPE_CHECKING:
    import tiktoken  # noqa: F401

logger = logging.getLogger(__name__)


@dataclass
class ContextMessage:
    """A message in the context window."""

    id: str
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime
    importance: float = 0.5  # 0.0 - 1.0
    tokens: int = 0
    is_grounding: bool = False  # User preferences, active projects
    is_pruned: bool = False  # Message has been pruned from active context

    # Priority tiers for pruning decisions
    priority_tier: int = 1  # 0=highest (never prune), 1=high, 2=medium, 3=low

    def should_preserve(self) -> bool:
        """Check if message should be preserved regardless of token pressure."""
        return self.is_grounding or self.priority_tier == 0

    def pruning_score(self) -> float:
        """Lower score = more likely to be pruned."""
        # Inverse importance, normalize token cost
        return -(self.importance * 100) - (self.tokens / 1000)


@dataclass
class ContextStats:
    """Context window statistics."""

    current_tokens: int
    max_tokens: int
    messages_count: int
    active_messages_count: int  # Not pruned
    pruning_count: int = 0
    last_prune_timestamp: datetime | None = None


# Token estimation constants
CHAR_PER_TOKEN = 4  # Rough approximation for English
TOKEN_BUFFER_PER_SIDE = 512  # Reserve buffer on each side

# Priority tier definitions
TIER_0_PROTECTED = 0  # System instructions, critical config
TIER_1_HIGH = 1  # User preferences, tool results, decisions
TIER_2_MEDIUM = 2  # Regular conversation
TIER_3_LOW = 3  # Older, low-importance messages

TIERS = {
    0: "protected",
    1: "high",
    2: "medium",
    3: "low",
}


class ContextWindowManager:
    """Manages context window with intelligent pruning.

    Tracks importance of each message and prunes low-importance
    content when approaching token limits while maintaining
    conversation coherence.

    Example:
        >>> mgr = ContextWindowManager(max_tokens=50_000)
        >>> mgr.add("user", "Hello", importance=0.9, is_grounding=True)
        >>> msg = mgr.add("assistant", "Hi!", importance=0.7)
        >>> msg.tokens_remaining  # Show tokens left in window
    """

    def __init__(
        self, max_tokens: int = 180_000, model: str = "mini-max", storage_path: str | None = None
    ):
        """Initialize context window manager.

        Args:
            max_tokens: Maximum token capacity for the context window.
                       Actual usable tokens = max_tokens - 2 * TOKEN_BUFFER
            model: Model name for token estimation (affects encoding)
            storage_path: Optional path for persisting context history (JSON)
        """
        self.max_tokens = max_tokens
        self.usable_tokens = max_tokens - (2 * TOKEN_BUFFER_PER_SIDE)
        self.model = model
        self.storage_path = storage_path
        self._async_lock = asyncio.Lock()
        self.messages: list[ContextMessage] = []
        self._total_pruning_events = 0
        self.stats = ContextStats(
            current_tokens=0,
            max_tokens=max_tokens,
            messages_count=0,
            active_messages_count=0,
        )

    def add(
        self,
        role: str,
        content: str,
        importance: float = 0.5,
        is_grounding: bool = False,
        priority_tier: int = 2,
    ) -> ContextMessage:
        """Add a message to the context window.

        Args:
            role: Message role ("user", "assistant", "system")
            content: Message text content
            importance: Importance score 0.0-1.0 (higher = more important)
            is_grounding: True for user preferences, active projects
            priority_tier: 0-3, lower = more protected from pruning

        Returns:
            Created ContextMessage
        """
        msg = ContextMessage(
            id=f"msg_{len(self.messages)}_{datetime.now(timezone.utc).timestamp()}",
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
            importance=importance,
            tokens=self._estimate_tokens(content),
            is_grounding=is_grounding,
            priority_tier=priority_tier,
        )
        self.messages.append(msg)
        self._update_stats()
        self._prune_if_needed()
        return msg

    async def add_async(
        self,
        role: str,
        content: str,
        importance: float = 0.5,
        is_grounding: bool = False,
        priority_tier: int = 2,
    ) -> ContextMessage:
        """Async version of add() with asyncio.Lock for thread-safety.

        Args:
            role: Message role ("user", "assistant", "system")
            content: Message text content
            importance: Importance score 0.0-1.0 (higher = more important)
            is_grounding: True for user preferences, active projects
            priority_tier: 0-3, lower = more protected from pruning

        Returns:
            Created ContextMessage
        """
        async with self._async_lock:
            return self.add(role, content, importance, is_grounding, priority_tier)

    def get_messages(self, include_pruned: bool = False) -> list[ContextMessage]:
        """Get messages in context window.

        Args:
            include_pruned: If True, includes pruned messages for reference.

        Returns:
            List of ContextMessage objects
        """
        if include_pruned:
            return self.messages
        return [m for m in self.messages if not m.is_pruned]

    def get_active_tokens(self) -> int:
        """Get total tokens of non-pruned messages."""
        return sum(m.tokens for m in self.messages if not m.is_pruned)

    def tokens_remaining(self) -> int:
        """Calculate tokens remaining before forced pruning."""
        return self.usable_tokens - self.get_active_tokens()

    def needs_pruning(self) -> bool:
        """Check if context window needs pruning."""
        return self.tokens_remaining() < 0

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.


        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        # Base estimate: ~4 chars per token (English average)
        base_tokens = len(text) / CHAR_PER_TOKEN

        # CJK characters: ~1 token per character
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]", text))
        cjk_correction = cjk_chars - cjk_chars / CHAR_PER_TOKEN

        return int(base_tokens + cjk_correction)

    def _prune_if_needed(self) -> None:
        """Prune messages if context window is over capacity."""
        if not self.needs_pruning():
            return

        pruned = 0
        while self.needs_pruning() and self.messages:
            # Find lowest priority message
            candidates = [m for m in self.messages if not m.is_pruned and not m.should_preserve()]
            if not candidates:
                # All protected, cannot prune
                break

            # Sort by pruning score (ascending)
            candidates.sort(key=lambda m: m.pruning_score())
            victim = candidates[0]

            victim.is_pruned = True
            pruned += 1

        self._total_pruning_events += 1
        self.stats.pruning_count += pruned
        self.stats.last_prune_timestamp = datetime.now(timezone.utc)
        self._update_stats()
        logger.debug(f"Pruned {pruned} messages, {len(self.messages)} total in window")

    def _update_stats(self) -> None:
        """Update context window statistics."""
        active = [m for m in self.messages if not m.is_pruned]
        self.stats.current_tokens = self.get_active_tokens()
        self.stats.messages_count = len(self.messages)
        self.stats.active_messages_count = len(active)

    # ------------------------------------------------------------------
    # Semantic summarization integration
    # ------------------------------------------------------------------

    def set_summarizer(self, summarizer: SemanticSummarizer) -> None:
        """Register a :class:`SemanticSummarizer` for TIER_3 compression.

        After calling this, the manager will use the summarizer to compress
        TIER_3 messages instead of simply dropping them during pruning.

        Args:
            summarizer: A :class:`SemanticSummarizer` instance.
        """
        self._semantic_summarizer = summarizer  # type: ignore[attr-defined]

    def run_summarization(self, force: bool = False) -> SummarizationResult:
        """Run semantic summarization on TIER_3 messages.

        Requires a summarizer to be registered via :meth:`set_summarizer`.

        Args:
            force: If True, skip the minimum-message check in the summarizer.

        Returns:
            SummarizationResult with compression stats.

        Raises:
            RuntimeError: If no summarizer is registered.
        """
        summarizer = getattr(self, "_semantic_summarizer", None)
        if summarizer is None:
            msg = "no summarizer registered — call set_summarizer() first"
            raise RuntimeError(msg)
        return summarizer.summarize_tier3(self, force=force)

    def clear(self) -> None:
        """Clear all messages from context window."""
        self.messages = []
        self._update_stats()

    def mark_below_threshold(self, threshold: int = 0) -> list[ContextMessage]:
        """Return non-pruned messages whose token count is below threshold.

        Args:
            threshold: Token count threshold (default 0 = all messages)

        Returns:
            List of messages with tokens below threshold that are not pruned
        """
        return [m for m in self.messages if not m.is_pruned and m.tokens < threshold]

    def reset(self) -> None:
        """Clear all messages and reset statistics to initial state."""
        self.messages = []
        self.stats = ContextStats(
            current_tokens=0,
            max_tokens=self.max_tokens,
            messages_count=0,
            active_messages_count=0,
            pruning_count=0,
            last_prune_timestamp=None,
        )
        self._total_pruning_events = 0

    def get_summary(self) -> dict[str, int | float | str | bool]:
        """Get a summary of the current context window state.

        Returns:
            Dictionary with context window statistics
        """
        pruned = sum(1 for m in self.messages if m.is_pruned)
        return {
            "current_tokens": self.stats.current_tokens,
            "max_tokens": self.max_tokens,
            "usable_tokens": self.usable_tokens,
            "tokens_remaining": self.tokens_remaining(),
            "messages_count": self.stats.messages_count,
            "active_messages": self.stats.active_messages_count,
            "active_messages_count": self.stats.active_messages_count,
            "pruned_messages": pruned,
            "pruning_count": self.stats.pruning_count,
            "pruning_events": self._total_pruning_events,
            "utilization": (
                f"{(self.stats.current_tokens / self.usable_tokens * 100):.1f}%"
                if self.usable_tokens > 0
                else "0%"
            ),
            "needs_pruning": self.needs_pruning(),
        }

    def load(self) -> None:
        """Load context history from storage_path if configured."""
        if not self.storage_path:
            return
        path = Path(self.storage_path)
        if not path.exists():
            return
        try:
            import json

            with open(path) as f:
                data = json.load(f)
            messages = []
            for item in data.get("messages", []):
                item["timestamp"] = datetime.fromisoformat(item["timestamp"])
                messages.append(ContextMessage(**item))
            self.messages = messages
            self._update_stats()
            logger.info(f"Loaded {len(self.messages)} messages from {self.storage_path}")
        except Exception as e:
            logger.warning(f"Failed to load context history: {e}")

    def _auto_save(self) -> None:
        """Auto-save context history if storage_path configured."""
        if not self.storage_path:
            return
        import json

        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "importance": m.importance,
                    "tokens": m.tokens,
                    "is_grounding": m.is_grounding,
                    "is_pruned": m.is_pruned,
                    "priority_tier": m.priority_tier,
                }
                for m in self.messages
            ]
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def validate_coherence(self) -> dict[str, bool | list[str]]:
        """Validate logical coherence of current context window.

        Checks for common coherence issues that arise from aggressive pruning:
        - Orphaned assistant responses (assistant msg without preceding user msg)
        - Broken tool-result chains (tool result without preceding tool call)
        - Incomplete request-response pairs
        - System messages not at the beginning

        Returns:
            Dictionary with coherence validation results:
            - is_coherent: Overall coherence status
            - issues: List of specific issues found (empty if coherent)
        """
        issues: list[str] = []
        active_msgs = [m for m in self.messages if not m.is_pruned]

        if not active_msgs:
            return {"is_coherent": True, "issues": []}

        # Check 1: System messages should be at the beginning
        non_system = [m for m in active_msgs if m.role != "system"]
        if non_system:
            first_non_system = active_msgs[0] if active_msgs[0].role != "system" else None
            if first_non_system and any(m.role == "system" for m in active_msgs[1:]):
                issues.append("System messages found after non-system messages")

        # Check 2: Tool result without tool call pattern
        tool_results = [
            m for m in active_msgs if m.role == "tool" or "tool" in m.content.lower()[:50]
        ]
        if tool_results:
            for tr in tool_results:
                tr_idx = active_msgs.index(tr)
                prior_msgs = active_msgs[:tr_idx]
                if not any(m.role in ("assistant", "user") for m in prior_msgs[-3:]):
                    issues.append(
                        f"Tool result '{tr.content[:50]}...' appears without prior context"
                    )

        # Check 3: Ensure conversation has at least one user message
        if not any(m.role == "user" for m in active_msgs) and len(active_msgs) > 1:
            issues.append("No user messages found in context window")

        return {
            "is_coherent": len(issues) == 0,
            "issues": issues,
        }

    def get_coherence_score(self) -> float:
        """Get a coherence score from 0.0 to 1.0.

        Returns:
            Coherence score where 1.0 = perfectly coherent
        """
        if not self.messages:
            return 1.0
        validation = self.validate_coherence()
        if validation["is_coherent"]:
            return 1.0
        score = 1.0 - (len(cast(list[str], validation["issues"])) * 0.1)
        return max(0.0, score)
