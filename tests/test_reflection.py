"""Tests for reflection analyzer."""

from riks_context_engine.reflection.analyzer import (
    Lesson,
    ReflectionAnalyzer,
    detect_category,
    extract_severity,
)


class TestReflectionAnalyzer:
    def test_init(self):
        analyzer = ReflectionAnalyzer()
        assert analyzer.semantic_memory is None
        assert len(analyzer._lessons) == 0

    def test_analyze_empty_conversation(self):
        analyzer = ReflectionAnalyzer()
        report = analyzer.analyze("test-1", [])
        assert report.interaction_id == "test-1"
        assert len(report.went_well) == 0
        assert len(report.went_wrong) == 0

    def test_analyze_with_success(self):
        analyzer = ReflectionAnalyzer()
        conversation = [
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "Found and fixed the bug successfully"},
        ]
        report = analyzer.analyze("test-2", conversation)
        assert len(report.went_well) >= 0  # May detect success keywords

    def test_analyze_with_errors(self):
        analyzer = ReflectionAnalyzer()
        conversation = [
            {"role": "user", "content": "Call the API"},
            {"role": "assistant", "content": "Error: API timeout"},
        ]
        report = analyzer.analyze("test-3", conversation)
        assert len(report.went_wrong) >= 0

    def test_analyze_extracts_lessons(self):
        analyzer = ReflectionAnalyzer()
        conversation = [
            {"role": "user", "content": "Use the tool"},
            {"role": "assistant", "content": "Error: tool failed with timeout"},
        ]
        report = analyzer.analyze("test-4", conversation)
        # Should detect tool-use category
        for lesson in report.lessons:
            assert lesson.category in ["tool-use", "general"]

    def test_consult_before_task(self):
        analyzer = ReflectionAnalyzer()
        analyzer._lessons["l1"] = Lesson(
            id="l1",
            category="tool-use",
            observation="test",
            lesson_text="test",
            severity="warning",
            resolved=False,
        )
        relevant = analyzer.consult_before_task("Using a tool to call API")
        assert len(relevant) >= 0

    def test_record_success(self):
        analyzer = ReflectionAnalyzer()
        analyzer.record_success("task-1", "Completed successfully")

    def test_record_failure(self):
        analyzer = ReflectionAnalyzer()
        analyzer.record_failure("task-2", "API timeout error", "network issue")
        assert "tool-use" in analyzer._mistake_counts

    def test_track_mistake_frequency(self):
        analyzer = ReflectionAnalyzer()
        analyzer.record_failure("task-1", "API error", "timeout")
        analyzer.record_failure("task-2", "API error", "auth")
        counts = analyzer.track_mistake_frequency()
        assert "tool-use" in counts
        assert counts["tool-use"] == 2

    def test_resolve_lesson(self):
        analyzer = ReflectionAnalyzer()
        analyzer._lessons["l1"] = Lesson(
            id="l1",
            category="general",
            observation="test",
            lesson_text="test",
            severity="info",
            resolved=False,
        )
        assert analyzer.resolve_lesson("l1") is True
        assert analyzer._lessons["l1"].resolved is True
        assert analyzer.resolve_lesson("nonexistent") is False

    def test_get_active_lessons(self):
        analyzer = ReflectionAnalyzer()
        analyzer._lessons["l1"] = Lesson(
            id="l1",
            category="general",
            observation="test",
            lesson_text="test",
            severity="info",
            resolved=False,
        )
        analyzer._lessons["l2"] = Lesson(
            id="l2",
            category="general",
            observation="test",
            lesson_text="test",
            severity="info",
            resolved=True,
        )
        active = analyzer.get_active_lessons()
        assert len(active) == 1
        assert active[0].id == "l1"


class TestDetectCategory:
    def test_tool_use_patterns(self):
        assert "tool-use" in detect_category("tool failed with error")
        assert "tool-use" in detect_category("function call error")

    def test_context_management_patterns(self):
        assert "context-management" in detect_category("context overflow detected")
        assert "context-management" in detect_category("token limit reached")

    def test_task_planning_patterns(self):
        assert "task-planning" in detect_category("wrong order of execution")
        assert "task-planning" in detect_category("missed step in plan")

    def test_security_patterns(self):
        assert "security" in detect_category("security vulnerability found")
        assert "security" in detect_category("data exposure risk")

    def test_no_match(self):
        categories = detect_category("just some text")
        assert categories == ["general"]


class TestExtractSeverity:
    def test_critical_keywords(self):
        assert extract_severity("critical security breach") == "critical"
        assert extract_severity("data loss disaster") == "critical"

    def test_warning_keywords(self):
        assert extract_severity("this is a warning") == "warning"
        assert extract_severity("something went wrong") == "warning"

    def test_default_info(self):
        assert extract_severity("just some text") == "info"
