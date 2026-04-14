"""Context window manager - intelligent pruning and coherence."""

from dataclasses import dataclass
from datetime import datetime, timezone


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


@dataclass
class ContextStats:
    """Context window statistics."""

    current_tokens: int
    max_tokens: int
    messages_count: int
    pruning_count: int = 0


class ContextWindowManager:
    """Manages context window with intelligent pruning.

    Tracks importance of each message and prunes low-importance
    content when approaching token limits while maintaining
    conversation coherence.
    """

    def __init__(self, max_tokens: int = 180_000, model: str = "mini-max"):
        self.max_tokens = max_tokens
        self.model = model
        self.messages: list[ContextMessage] = []
        self.stats = ContextStats(current_tokens=0, max_tokens=max_tokens, messages_count=0)

    def add(
        self,
        role: str,
        content: str,
        importance: float = 0.5,
        is_grounding: bool = False,
    ) -> ContextMessage:
        """Add a message to the context window."""
        msg = ContextMessage(
            id=f"msg_{len(self.messages)}",
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
            importance=importance,
            tokens=self._estimate_tokens(content),
            is_grounding=is_grounding,
        )
        self.messages.append(msg)
        self._update_stats()
        self._prune_if_needed()
        return msg

    def get_messages(self) -> list[ContextMessage]:
        """Get all messages in context window."""
        return self.messages

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4

    def _update_stats(self) -> None:
        """Update context statistics."""
        self.stats = ContextStats(
            current_tokens=sum(m.tokens for m in self.messages),
            max_tokens=self.max_tokens,
            messages_count=len(self.messages),
        )

    def _prune_if_needed(self) -> None:
        """Prune low-importance messages when approaching limits."""
        pass  # TODO: implement pruning algorithm

    def validate_coherence(self) -> bool:
        """Validate conversation coherence after pruning."""
        return True  # TODO: implement coherence validator
