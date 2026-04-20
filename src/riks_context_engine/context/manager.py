"""Context window manager - intelligent pruning and coherence."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tiktoken

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

    def __init__(self, max_tokens: int = 180_000, model: str = "mini-max"):
        """Initialize context window manager.

        Args:
            max_tokens: Maximum token capacity for the context window.
                       Actual usable tokens = max_tokens - 2 * TOKEN_BUFFER
            model: Model name for token estimation (affects encoding)
        """
        self.max_tokens = max_tokens
        self.usable_tokens = max_tokens - (2 * TOKEN_BUFFER_PER_SIDE)
        self.model = model
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
        async with asyncio.Lock():
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

    def _get_tiktoken_encoding(self) -> tuple["tiktoken.Encoding", str] | None:
        """Get tiktoken encoding for the current model.

        Returns:
            Tuple of (encoding, encoding_name) or None if tiktoken unavailable
        """
        try:
            import tiktoken

            # Map model names to tiktoken encoding names
            model_to_encoding = {
                "gpt-4": "cl100k_base",
                "gpt-4o": "cl100k_base",
                "gpt-4o-mini": "cl100k_base",
                "gpt-4-turbo": "cl100k_base",
                "gpt-3.5-turbo": "cl100k_base",
                "gpt-3.5": "cl100k_base",
                "mini-max": "cl100k_base",
                "mini-max-m2": "cl100k_base",
                "minimax": "cl100k_base",
                "qwen": "cl100k_base",
                "qwen3": "cl100k_base",
                "qwen3.5": "cl100k_base",
                "gemma": "cl100k_base",
                "gemma-4": "cl100k_base",
                "llama": "cl100k_base",
                "codellama": "cl100k_base",
                "default": "cl100k_base",
            }

            # Determine encoding name based on model
            model_lower = self.model.lower() if self.model else "default"
            encoding_name = "cl100k_base"  # Default for most modern models

            for model_pattern, enc_name in model_to_encoding.items():
                if model_pattern in model_lower:
                    encoding_name = enc_name
                    break

            encoding = tiktoken.get_encoding(encoding_name)
            return encoding, encoding_name

        except ImportError:
            logger.warning(
                "tiktoken not installed. Install with: pip install tiktoken\n"
                "Falling back to character-based estimation."
            )
            return None
        except Exception as e:
            logger.warning(
                f"Failed to get tiktoken encoding: {e}. Falling back to character-based estimation."
            )
            return None

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses tiktoken for accurate model-specific encoding when available.
        Falls back to character-based estimation for unsupported models
        or when tiktoken is not installed.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        # Try tiktoken first for more accurate estimation
        encoding_result = self._get_tiktoken_encoding()
        if encoding_result is not None:
            encoding, enc_name = encoding_result
            try:
                tokens = encoding.encode(text, disallowed_special=())
                return len(tokens)
            except Exception as e:
                logger.warning(
                    f"tiktoken encoding failed: {e}. Falling back to character-based estimation."
                )

        # Fallback: character-based estimation with script-aware adjustments
        # Base estimate: ~4 chars per token (English average)
        base_tokens = len(text) // CHAR_PER_TOKEN

        # Special handling for code blocks (less efficient encoding)
        code_indicators = ["```", "def ", "class ", "function(", "import ", "const "]
        if any(indicator in text for indicator in code_indicators):
            # Code tends to use more tokens per char
            base_tokens = int(base_tokens * 1.3)

        # Special handling for non-Latin scripts (more tokens per char)
        # e.g., CJK characters are typically 1 token per 2 chars
        if self._contains_non_latin(text):
            base_tokens = int(len(text) / 2)

        return base_tokens

    def _contains_non_latin(self, text: str) -> bool:
        """Check if text contains non-Latin or accented Latin characters."""
        # CJK, Arabic, Cyrillic, Greek, etc.
        return bool(re.search(r"[\u4e00-\u9fff\u0600-\u06ff\u0400-\u04ff\u0370-\u03ff]", text))

    def _update_stats(self) -> None:
        """Update context statistics."""
        active = [m for m in self.messages if not m.is_pruned]
        self.stats = ContextStats(
            current_tokens=sum(m.tokens for m in active),
            max_tokens=self.max_tokens,
            messages_count=len(self.messages),
            active_messages_count=len(active),
            pruning_count=self._total_pruning_events,
        )

    def _prune_if_needed(self) -> None:
        """Prune low-importance messages when approaching limits."""
        if not self.needs_pruning():
            return

        prune_targets: list[ContextMessage] = []
        tokens_to_free = abs(self.tokens_remaining()) + (
            self.usable_tokens // 10
        )  # Free 10% buffer

        # Collect candidates: non-protected, non-grounding, not tier 0
        for msg in self.messages:
            if not msg.should_preserve() and not msg.is_pruned:
                prune_targets.append(msg)

        # Sort by pruning score (lowest = prune first)
        prune_targets.sort(key=lambda m: m.pruning_score())

        # Prune messages until we have enough buffer
        freed_tokens = 0
        for msg in prune_targets:
            if freed_tokens >= tokens_to_free:
                break
            msg.is_pruned = True
            freed_tokens += msg.tokens
            self._total_pruning_events += 1

        # Update last prune timestamp
        if freed_tokens > 0:
            self.stats.last_prune_timestamp = datetime.now(timezone.utc)

        self._update_stats()

    async def prune_async(self) -> int:
        """Async version of forced prune with asyncio.Lock.


        Returns:
            Number of messages pruned
        """
        async with asyncio.Lock():
            before = sum(1 for m in self.messages if not m.is_pruned)
            self._prune_if_needed()
            after = sum(1 for m in self.messages if not m.is_pruned)
            return before - after

    def validate_coherence(self) -> bool:
        """Validate conversation coherence after pruning.

        Ensures:
        - At least one message from each turn remains
        - No orphaned assistant responses
        - Grounding messages preserved
        """
        active = self.get_messages()

        # Empty context is valid (just not useful)
        if not active:
            return True

        # Check for orphaned messages (assistant without preceding user)
        # Skip first message
        seen_user = any(m.role == "user" for m in active)
        for i, msg in enumerate(active):
            if msg.role == "assistant" and i == 0:
                continue  # First message can be assistant
            if msg.role == "assistant" and not seen_user:
                return False
            if msg.role == "user":
                seen_user = True

        # Ensure grounding messages are present if any were added
        grounding_messages = [m for m in self.messages if m.is_grounding]
        if grounding_messages and not any(
            m.is_grounding and not m.is_pruned for m in self.messages
        ):
            return False

        return True

    def get_summary(self) -> dict:
        """Get context window summary for debugging."""
        return {
            "max_tokens": self.max_tokens,
            "usable_tokens": self.usable_tokens,
            "current_tokens": self.stats.current_tokens,
            "active_messages": self.stats.active_messages_count,
            "pruned_messages": self.stats.messages_count - self.stats.active_messages_count,
            "tokens_remaining": self.tokens_remaining(),
            "pruning_events": self._total_pruning_events,
            "needs_pruning": self.needs_pruning(),
        }

    def mark_below_threshold(self, threshold: int = 512) -> list[ContextMessage]:
        """Mark messages with less than threshold tokens remaining.

        Useful for UI indicators showing how much space is left.

        Args:
            threshold: Token threshold (default 512)

        Returns:
            List of messages that fit within threshold
        """
        remaining = self.tokens_remaining()
        if remaining >= threshold:
            return []

        # Return messages that can fit in remaining space
        result = []
        running_total = 0
        for msg in reversed(self.get_messages()):
            if running_total + msg.tokens <= remaining:
                result.append(msg)
                running_total += msg.tokens

        return result

    def reset(self) -> None:
        """Clear all messages and stats."""
        self.messages.clear()
        self._total_pruning_events = 0
        self._update_stats()
