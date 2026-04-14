"""Context window manager - intelligent pruning and coherence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# -------------------------------------------------------------------
# Importance Scorer
# -------------------------------------------------------------------

class ImportanceScorer:
    """Scores message importance based on content analysis.

    Scoring dimensions:
    - user_mentions   : User explicitly refers to something important
    - new_information : Message introduces new facts or data
    - decisions       : Message captures a decision or commitment
    - tool_result     : Tool output (usually worth preserving)
    """

    # Patterns that indicate high importance
    DECISION_PATTERNS = [
        re.compile(r"\b(decided|decision|chose|choice|agreed|will do|going to)\b", re.I),
        re.compile(r"\b(important|remember|must|never|always)\b", re.I),
        re.compile(r"\b(todo|task|goal|plan|schedule)\b", re.I),
        re.compile(r"\b(create|delete|update|fix|build|implement)\b", re.I),
        re.compile(r"\bcommit\s+(to|that)\b", re.I),
        re.compile(r"\b(i'?ll|i will|we should|let'?s)\b", re.I),
    ]

    NEW_INFO_PATTERNS = [
        re.compile(r"\b(learned|found|discovered|realized|figured out)\b", re.I),
        re.compile(r"\b(result|output|response|answer|returned)\b", re.I),
        re.compile(r"\b(error|typeerror|exception|failed|crashed|issue|bug)\b", re.I),
        re.compile(r"\b(ip|address|port|token|key|config)\b", re.I),
        re.compile(r"\b(http|localhost|127\.0\.0\.1|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", re.I),
    ]

    USER_MENTION_PATTERNS = [
        re.compile(r"\b(prefer|preference|hate|like|want|need|don.t)\b", re.I),
        re.compile(r"\b(prefer|preference|hate|like|want|need|don.t)\b", re.I),
        re.compile(r"\b(never|always|every time|never again)\b", re.I),
        re.compile(r"\b(user|account|profile|settings|preferences)\b", re.I),
    ]

    TOOL_RESULT_INDICATORS = [
        "tool_use", "tool_call", "function_call",
        "<function>", "<tool>", "```output",
    ]

    @classmethod
    def score(cls, content: str, role: str) -> tuple[float, dict[str, float]]:
        """Calculate importance score for a message.

        Args:
            content: Message text content
            role: Message role ("user", "assistant", "system", "tool")

        Returns:
            Tuple of (overall_score 0.0-1.0, dimension_scores dict)
        """
        dims = {
            "user_mentions": cls._score_user_mentions(content),
            "new_information": cls._score_new_info(content),
            "decisions": cls._score_decisions(content),
            "tool_result": cls._score_tool_result(content, role),
        }

        # Weighted average
        weights = {"user_mentions": 0.35, "new_information": 0.25, "decisions": 0.25, "tool_result": 0.15}
        overall = sum(dims[k] * weights[k] for k in weights)

        return (round(overall, 3), dims)

    @classmethod
    def _score_user_mentions(cls, content: str) -> float:
        score = 0.0
        for pat in cls.USER_MENTION_PATTERNS:
            if pat.search(content):
                score += 0.3
        return min(score, 1.0)

    @classmethod
    def _score_new_info(cls, content: str) -> float:
        score = 0.0
        for pat in cls.NEW_INFO_PATTERNS:
            if pat.search(content):
                score += 0.25
        return min(score, 1.0)

    @classmethod
    def _score_decisions(cls, content: str) -> float:
        score = 0.0
        for pat in cls.DECISION_PATTERNS:
            if pat.search(content):
                score += 0.3
        return min(score, 1.0)

    @classmethod
    def _score_tool_result(cls, content: str, role: str) -> float:
        if role in ("tool", "system"):
            return 0.8
        for indicator in cls.TOOL_RESULT_INDICATORS:
            if indicator in content:
                return 0.6
        return 0.0

    @classmethod
    def auto_importance(cls, content: str, role: str) -> float:
        """Convenience: returns just the overall importance score."""
        score, _ = cls.score(content, role)
        return score


# -------------------------------------------------------------------
# Context Message & Stats
# -------------------------------------------------------------------

@dataclass
class ContextMessage:
    """A message in the context window."""

    id: str
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: datetime
    importance: float = 0.5  # 0.0 - 1.0
    tokens: int = 0
    is_grounding: bool = False  # User preferences, active projects
    is_pruned: bool = False  # Message has been pruned from active context

    # Importance dimension breakdown (for debugging/auditing)
    importance_dims: dict[str, float] = field(default_factory=dict)

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
    usage_percent: float = 0.0  # Derived: current_tokens / max_tokens
    pruning_count: int = 0
    last_prune_timestamp: Optional[datetime] = None


# Token estimation constants
CHAR_PER_TOKEN = 4  # Rough approximation for English
TOKEN_BUFFER_PER_SIDE = 512  # Reserve buffer on each side

# Priority tier definitions
TIER_0_PROTECTED = 0  # System instructions, critical config
TIER_1_HIGH = 1      # User preferences, tool results, decisions
TIER_2_MEDIUM = 2    # Regular conversation
TIER_3_LOW = 3       # Older, low-importance messages

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

        Uses character-based estimation as approximation.
        More accurate with tiktoken when available.

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
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
        """Check if text contains non-Latin characters."""
        import re
        # CJK, Arabic, Cyrillic, etc.
        return bool(re.search(r'[\u4e00-\u9fff\u0600-\u06ff\u0400-\u04ff]', text))

    def _update_stats(self) -> None:
        """Update context statistics."""
        active = [m for m in self.messages if not m.is_pruned]
        current = sum(m.tokens for m in active)
        usage_pct = (current / self.max_tokens * 100) if self.max_tokens > 0 else 0.0
        self.stats = ContextStats(
            current_tokens=current,
            max_tokens=self.max_tokens,
            messages_count=len(self.messages),
            active_messages_count=len(active),
            usage_percent=round(usage_pct, 2),
            pruning_count=self._total_pruning_events,
        )

    def _prune_if_needed(self) -> None:
        """Prune low-importance messages when approaching limits."""
        if not self.needs_pruning():
            return

        prune_targets: list[ContextMessage] = []
        tokens_to_free = abs(self.tokens_remaining()) + (self.usable_tokens // 10)  # Free 10% buffer

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

    def validate_coherence(self) -> tuple[bool, float]:
        """Validate conversation coherence after pruning.

        Ensures:
        - At least one message from each turn remains
        - No orphaned assistant responses
        - Grounding messages preserved

        Returns:
            Tuple of (is_valid: bool, coherence_score: float 0.0-1.0)
        """
        active = self.get_messages()

        # Empty context is valid (just not useful)
        if not active:
            return (True, 1.0)

        # Check for orphaned messages (assistant without preceding user)
        seen_user = any(m.role == "user" for m in active)
        orphaned = False
        for i, msg in enumerate(active):
            if msg.role == "assistant" and i == 0:
                continue  # First message can be assistant
            if msg.role == "assistant" and not seen_user:
                orphaned = True
                break
            if msg.role == "user":
                seen_user = True

        # Ensure grounding messages are present if any were added
        grounding_messages = [m for m in self.messages if m.is_grounding]
        grounding_lost = bool(grounding_messages and not any(
            m.is_grounding and not m.is_pruned for m in self.messages
        ))

        # Check for consecutive same-role messages (unusual but sometimes valid)
        consecutive_breaks = 0
        for i in range(1, len(active)):
            if active[i].role == active[i - 1].role and active[i].role not in ("system", "tool"):
                consecutive_breaks += 1

        # Calculate coherence score
        is_valid = not orphaned and not grounding_lost

        # Score components (each reduces score)
        score = 1.0
        if orphaned:
            score -= 0.4
        if grounding_lost:
            score -= 0.4
        # Penalize consecutive same-role (excluding system/tool)
        total_pairs = max(len(active) - 1, 1)
        consecutive_ratio = consecutive_breaks / total_pairs
        score -= consecutive_ratio * 0.2

        return (is_valid, round(max(score, 0.0), 3))

    def get_usage_percent(self) -> float:
        """Get context usage as a percentage of max_tokens.

        Returns:
            Usage percentage (0.0 - 100.0+), can exceed 100 when over-provisioned.
        """
        return self.stats.usage_percent

    def get_pruning_recommendation(self) -> dict[str, any]:
        """Get a recommendation on pruning action.

        Analyzes current context state and returns a recommendation dict
        with action level, tokens_to_free, and priority targets.

        Returns:
            Dict with recommendation details
        """
        usage = self.get_usage_percent()
        remaining = self.tokens_remaining()

        if usage < 60:
            level = "none"
            tokens_to_free = 0
        elif usage < 80:
            level = "advisory"
            tokens_to_free = int(self.max_tokens * 0.10)
        elif usage < 95:
            level = "recommended"
            tokens_to_free = int(self.max_tokens * 0.20)
        else:
            level = "critical"
            tokens_to_free = remaining + int(self.max_tokens * 0.15)

        # Suggest which priority tiers to target
        tier_targets = []
        if level in ("advisory", "recommended", "critical"):
            tier_targets = [3]  # Always start with tier 3
            if level in ("recommended", "critical"):
                tier_targets.append(2)
            if level == "critical":
                tier_targets.append(1)  # Only in emergencies

        return {
            "level": level,
            "usage_percent": usage,
            "tokens_to_free": max(tokens_to_free, 0),
            "tokens_remaining": remaining,
            "tier_targets": tier_targets,
            "urgent": level == "critical",
        }

    def get_summary(self) -> dict:
        """Get context window summary for debugging."""
        coherence_valid, coherence_score = self.validate_coherence()
        return {
            "max_tokens": self.max_tokens,
            "usable_tokens": self.usable_tokens,
            "current_tokens": self.stats.current_tokens,
            "active_messages": self.stats.active_messages_count,
            "pruned_messages": self.stats.messages_count - self.stats.active_messages_count,
            "tokens_remaining": self.tokens_remaining(),
            "usage_percent": self.stats.usage_percent,
            "pruning_events": self._total_pruning_events,
            "needs_pruning": self.needs_pruning(),
            "coherence_valid": coherence_valid,
            "coherence_score": coherence_score,
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

    def auto_score_and_add(
        self,
        role: str,
        content: str,
        is_grounding: bool = False,
        priority_tier: int = 2,
    ) -> ContextMessage:
        """Add a message with automatic importance scoring.

        Uses ImportanceScorer to analyze content and assign importance
        before adding to context window.

        Args:
            role: Message role ("user", "assistant", "system", "tool")
            content: Message text content
            is_grounding: True for user preferences, active projects
            priority_tier: 0-3, lower = more protected from pruning

        Returns:
            Created ContextMessage with auto-calculated importance
        """
        importance, dims = ImportanceScorer.score(content, role)
        msg = ContextMessage(
            id=f"msg_{len(self.messages)}_{datetime.now(timezone.utc).timestamp()}",
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
            importance=importance,
            importance_dims=dims,
            tokens=self._estimate_tokens(content),
            is_grounding=is_grounding,
            priority_tier=priority_tier,
        )
        self.messages.append(msg)
        self._update_stats()
        self._prune_if_needed()
        return msg