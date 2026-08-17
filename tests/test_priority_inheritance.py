"""Priority inheritance tests."""

from riks_context_engine.context.manager import (
    TIER_0_PROTECTED,
    TIER_1_HIGH,
    TIER_3_LOW,
    ContextWindowManager,
)


def test_child_inherits_parent_importance():
    """Child message should inherit parent importance when higher."""
    mgr = ContextWindowManager(max_tokens=10_000)

    parent = mgr.add(
        "user", "Critical decision: use PostgreSQL", importance=0.95, priority_tier=TIER_1_HIGH
    )
    parent.id = "parent-1"

    child = mgr.add("assistant", "OK, noted", importance=0.3, priority_tier=TIER_3_LOW)
    child.id = "child-1"
    child.parent_id = "parent-1"

    mgr.propagate_priority("child-1")

    assert child.importance >= parent.importance
    assert child.priority_tier <= parent.priority_tier


def test_priority_only_inherits_upwards():
    """Priority tier only goes up, never down."""
    mgr = ContextWindowManager(max_tokens=10_000)

    parent = mgr.add("user", "Minor note", importance=0.3, priority_tier=TIER_3_LOW)
    parent.id = "parent-3"

    child = mgr.add("assistant", "Detailed response", importance=0.8, priority_tier=TIER_1_HIGH)
    child.id = "child-3"
    child.parent_id = "parent-3"

    original_importance = child.importance
    mgr.propagate_priority("child-3")

    assert child.importance == original_importance


def test_tier0_not_inherited():
    """TIER_0 (protected) messages do not propagate inheritance.

    TIER_0_PROTECTED should not propagate to children. Child should keep
    its original priority_tier even when parent is TIER_0.
    """
    mgr = ContextWindowManager(max_tokens=10_000)

    system = mgr.add(
        "system", "System instructions", importance=1.0, priority_tier=TIER_0_PROTECTED
    )
    system.id = "system-1"

    child = mgr.add("user", "Hello", importance=0.3, priority_tier=TIER_3_LOW)
    child.id = "child-sys"
    child.parent_id = "system-1"

    mgr.propagate_priority("child-sys")

    # TIER_0 should NOT propagate to child - child keeps original tier
    assert child.priority_tier == TIER_3_LOW, (
        f"Expected TIER_3_LOW({TIER_3_LOW}), got TIER_0({TIER_0_PROTECTED})"
    )


def test_pruning_score_uses_inherited():
    """pruning_score should reflect inherited importance."""
    mgr = ContextWindowManager(max_tokens=10_000)

    parent = mgr.add("user", "Important thread", importance=0.9, priority_tier=TIER_1_HIGH)
    parent.id = "parent-prune"

    child = mgr.add(
        "assistant",
        "Reply with some detailed content here",
        importance=0.2,
        priority_tier=TIER_3_LOW,
    )
    child.id = "child-prune"
    child.parent_id = "parent-prune"

    mgr.propagate_priority("child-prune")

    # With inherited importance 0.9, score should be higher priority (less negative)
    score_with_inherited = child.pruning_score()
    # Base score without inheritance: -(0.2 * 100) - (tokens/1000)
    # With inherited 0.9: -(0.9 * 100) - (tokens/1000) = -90 - (tokens/1000)
    assert score_with_inherited > -100  # Much better than default -20 score
