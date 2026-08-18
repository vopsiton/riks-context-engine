"""Integration tests for the reflection analyzer's LLM path (issue #126).

These tests mock the Ollama client (``ollama.Client``) so the LLM path is
deterministic and hermetic, covering three distinct conversation contents:

1. A debugging session with tool/API failures and a resolution.
2. A task-planning session with wrong ordering and missed steps.
3. A security-incident session with a critical exposure.

Plus: invalid-JSON fallback, connection-failure fallback, and config
defaults (OLLAMA_MODEL / OLLAMA_BASE_URL env vars).
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from riks_context_engine.reflection.analyzer import (
    _REFLECT_SYSTEM_PROMPT,
    _REFLECT_USER_PROMPT,
    ReflectionAnalyzer,
    _render_conversation,
)

# ---------------------------------------------------------------------------
# Fake ollama package
# ---------------------------------------------------------------------------


def _install_fake_ollama(fake_ollama: types.ModuleType | None) -> None:
    if fake_ollama is not None:
        sys.modules["ollama"] = fake_ollama
    else:
        sys.modules.pop("ollama", None)


def _make_fake_ollama_pairs(pairs) -> types.ModuleType:
    """Build a fake ``ollama`` module whose Client.chat picks the LLM
    response whose marker appears in the user prompt content.

    Accepts either a single ``(marker, response)`` pair or a tuple of pairs.
    """
    if isinstance(pairs[0], str):
        pairs = (pairs,)

    class FakeMessage:
        def __init__(self, content: str):
            self.content = content

    class FakeResponse:
        def __init__(self, content: str):
            self.message = FakeMessage(content)

    def _user_content(messages) -> str:
        return messages[1]["content"] if len(messages) > 1 else ""

    class FakeClient:
        def __init__(self, host=None, timeout=None, **kwargs):
            self.host = host
            self.timeout = timeout

        def chat(self, model, messages, options=None):
            marker = next((m for m, _r in pairs if m in _user_content(messages)), None)
            if marker is None:
                return FakeResponse("ERROR: unexpected conversation")
            return FakeResponse(dict(pairs)[marker])

    module = types.ModuleType("ollama")
    module.Client = FakeClient  # type: ignore[attr-defined]
    return module


@pytest.fixture
def no_ollama():
    """Make the real ollama package unimportable (force fallback).

    Pops the module AND any loaded submodules so a later ``import ollama``
    resolves to a module missing the ``Client`` attribute (ImportError).
    """
    loaded = [k for k in sys.modules if k == "ollama" or k.startswith("ollama.")]
    saved = {k: sys.modules[k] for k in loaded}
    for k in loaded:
        del sys.modules[k]
    yield
    sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Test conversations (distinct contents)
# ---------------------------------------------------------------------------

CONVERSATION_DEBUGGING = [
    {"role": "user", "content": "Deploy the payment service to staging"},
    {
        "role": "assistant",
        "content": "I ran the deploy script but it failed with: Error: API timeout on /v1/checkout",
    },
    {"role": "user", "content": "Check the timeout config and retry with a longer window"},
    {
        "role": "assistant",
        "content": "Increased the timeout in config.yaml and redeployed. Success: all endpoints healthy now.",
    },
]

CONVERSATION_PLANNING = [
    {"role": "user", "content": "Migrate the database to the new schema"},
    {
        "role": "assistant",
        "content": "I ran the migration before backing up the database, which was the wrong order.",
    },
    {
        "role": "assistant",
        "content": "The migration missed step 3 (index rebuild) and left a dependency broken on the orders table.",
    },
    {"role": "user", "content": "Roll back and redo it: backup first, then migrate, then rebuild indexes"},
]

CONVERSATION_SECURITY = [
    {"role": "user", "content": "The admin panel is showing an error page"},
    {
        "role": "assistant",
        "content": "I found the database password was hardcoded in app.py and exposed in the error traceback.",
    },
    {
        "role": "user",
        "content": "Rotate the credential immediately and fix the validation so the error message does not leak data.",
    },
]

# ---------------------------------------------------------------------------
# LLM responses (deterministic, distinct per conversation)
# ---------------------------------------------------------------------------

LLM_RESPONSE_DEBUGGING = json.dumps(
    {
        "went_well": [
            "Retrying the deploy after adjusting the timeout in config.yaml succeeded and endpoints are healthy."
        ],
        "went_wrong": [
            "The deploy script failed with an API timeout on /v1/checkout before the timeout was increased."
        ],
        "missing_info": [
            "The configured timeout value for the checkout API was not known initially."
        ],
        "lessons": [
            {
                "category": "tool-use",
                "observation": "Deploy script failed with API timeout on /v1/checkout.",
                "lesson_text": "Increase the API timeout window before deploying to staging when the target endpoint is slow.",
                "severity": "warning",
            }
        ],
    }
)

LLM_RESPONSE_PLANNING = json.dumps(
    {
        "went_well": ["A rollback plan was agreed on with the correct step order."],
        "went_wrong": [
            "The database migration was run before the backup, in the wrong order.",
            "Step 3 (index rebuild) was missed, breaking a dependency on the orders table."
        ],
        "missing_info": ["The full migration checklist was not available to the agent."],
        "lessons": [
            {
                "category": "task-planning",
                "observation": "Migration executed before backup; wrong order of steps.",
                "lesson_text": "Always back up the database before running a schema migration.",
                "severity": "critical",
            },
            {
                "category": "task-planning",
                "observation": "Missed step 3 (index rebuild) left a dependency broken.",
                "lesson_text": "Verify every migration step, including index rebuilds, before declaring the task done.",
                "severity": "warning",
            },
        ],
    }
)

LLM_RESPONSE_SECURITY = json.dumps(
    {
        "went_well": [],
        "went_wrong": [
            "The database password was hardcoded in app.py and exposed in an error traceback."
        ],
        "missing_info": ["It was unclear how the credential was originally stored."],
        "lessons": [
            {
                "category": "security",
                "observation": "Credential exposed in an error traceback.",
                "lesson_text": "Never hardcode credentials; rotate any exposed credential immediately and sanitize error pages.",
                "severity": "critical",
            }
        ],
    }
)


def _responses_by_content(*pairs: tuple[str, str]):
    """Return the (marker, response) pairs for _make_fake_ollama_pairs."""
    return pairs


# ---------------------------------------------------------------------------
# Integration tests (LLM path, mocked Ollama)
# ---------------------------------------------------------------------------


class TestReflectionLLMIntegration:
    """analyze() must perform a real (mocked) LLM call and produce a
    structured, content-based report for distinct session contents."""

    def test_debugging_session(self, tmp_path):
        _install_fake_ollama(_make_fake_ollama_pairs(("/v1/checkout", LLM_RESPONSE_DEBUGGING)))
        try:
            analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
            report = analyzer.analyze("int-debug", CONVERSATION_DEBUGGING)
        finally:
            _install_fake_ollama(None)

        assert report.source == "llm"
        assert report.interaction_id == "int-debug"
        # Structured output is content-based, not just metadata
        assert any("/v1/checkout" in w for w in report.went_wrong)
        assert any("timeout" in w.lower() or "config.yaml" in w for w in report.went_well)
        assert len(report.lessons) == 1
        lesson = report.lessons[0]
        assert lesson.category == "tool-use"
        assert lesson.severity == "warning"
        assert "/v1/checkout" in lesson.observation
        # Lessons are consumed by consult_before_task
        relevant = analyzer.consult_before_task("Deploy and call the checkout API")
        assert any(lsn.id == lesson.id for lsn in relevant)
        # Persistence happened (real file write on the LLM path)
        assert (tmp_path / "lessons.json").exists()

    def test_planning_session(self, tmp_path):
        _install_fake_ollama(_make_fake_ollama_pairs(("wrong order", LLM_RESPONSE_PLANNING)))
        try:
            analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
            report = analyzer.analyze("int-plan", CONVERSATION_PLANNING)
        finally:
            _install_fake_ollama(None)

        assert report.source == "llm"
        assert len(report.went_wrong) == 2
        assert any("backup" in w for w in report.went_wrong)
        assert len(report.lessons) == 2
        severities = {lsn.severity for lsn in report.lessons}
        assert severities == {"critical", "warning"}
        assert all(lsn.category == "task-planning" for lsn in report.lessons)
        # Critical planning lesson is surfaced when consulting a similar task
        relevant = analyzer.consult_before_task("Migrate the database, wrong order risk")
        assert len(relevant) >= 1
        assert any(lsn.severity == "critical" for lsn in relevant)

    def test_security_session(self, tmp_path):
        _install_fake_ollama(_make_fake_ollama_pairs(("hardcoded", LLM_RESPONSE_SECURITY)))
        try:
            analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
            report = analyzer.analyze("int-sec", CONVERSATION_SECURITY)
        finally:
            _install_fake_ollama(None)

        assert report.source == "llm"
        assert report.went_well == []
        assert any("password" in w for w in report.went_wrong)
        assert len(report.lessons) == 1
        lesson = report.lessons[0]
        assert lesson.category == "security"
        assert lesson.severity == "critical"
        relevant = analyzer.consult_before_task("Fix an unauthorized data exposure")
        assert any(lsn.id == lesson.id for lsn in relevant)

    def test_markdown_fenced_json_is_stripped(self, tmp_path):
        fenced = "```json\n" + LLM_RESPONSE_DEBUGGING + "\n```"
        _install_fake_ollama(_make_fake_ollama_pairs(("/v1/checkout", fenced)))
        try:
            analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
            report = analyzer.analyze("int-fenced", CONVERSATION_DEBUGGING)
        finally:
            _install_fake_ollama(None)

        assert report.source == "llm"
        assert len(report.lessons) == 1

    def test_malformed_llm_json_falls_back(self, tmp_path):
        _install_fake_ollama(_make_fake_ollama_pairs(("/v1/checkout", "I cannot answer that.")))
        try:
            analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
            report = analyzer.analyze("int-bad-json", CONVERSATION_DEBUGGING)
        finally:
            _install_fake_ollama(None)

        assert report.source == "fallback"
        # Fallback is still content-based: it found the failure text
        assert any("/v1/checkout" in w for w in report.went_wrong)
        assert len(report.lessons) >= 1


# ---------------------------------------------------------------------------
# Fallback tests (deterministic, no Ollama)
# ---------------------------------------------------------------------------


class TestReflectionFallback:
    def test_ollama_connection_failure_uses_fallback(self, no_ollama, tmp_path):
        # No fake module and no real Ollama dependency path: the client is
        # pointed at an unused port so any importable ollama would fail too.
        analyzer = ReflectionAnalyzer(
            storage_path=str(tmp_path / "lessons.json"),
            llm_base_url="http://127.0.0.1:1",
            llm_timeout=1.0,
        )
        report = analyzer.analyze("int-offline", CONVERSATION_DEBUGGING)
        assert report.source == "fallback"
        assert any("/v1/checkout" in w for w in report.went_wrong)
        assert len(report.went_wrong) >= 1
        assert len(report.lessons) >= 1
        # Fallback summarizes the most important N messages
        assert report.went_well or report.went_wrong or report.missing_info

    def test_fallback_content_based_summary(self, no_ollama, tmp_path):
        analyzer = ReflectionAnalyzer(
            storage_path=str(tmp_path / "lessons.json"), fallback_top_n=3
        )
        report = analyzer.analyze("int-fb", CONVERSATION_PLANNING)
        assert report.source == "fallback"
        # The important failure messages are surfaced, not just metadata
        assert any("wrong order" in w for w in report.went_wrong)
        assert any("missed step 3" in w for w in report.went_wrong)
        assert any(lsn.category == "task-planning" for lsn in report.lessons)
        assert any(lsn.severity == "warning" for lsn in report.lessons)

    def test_neutral_conversation_still_summarized(self, no_ollama, tmp_path):
        conversation = [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
        ]
        analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
        report = analyzer.analyze("int-neutral", conversation)
        assert report.source == "fallback"
        # Even without keyword signals, the top messages are summarized
        assert len(report.lessons) >= 1
        assert any("Paris" in lsn.observation or "France" in lsn.observation for lsn in report.lessons)

    def test_empty_conversation(self, no_ollama):
        analyzer = ReflectionAnalyzer()
        report = analyzer.analyze("int-empty", [])
        assert report.source == "fallback"
        assert report.went_well == []
        assert report.went_wrong == []
        assert report.lessons == []

    def test_lesson_consumption_roundtrip(self, no_ollama, tmp_path):
        """Lessons produced by analyze() feed consult_before_task."""
        analyzer = ReflectionAnalyzer(storage_path=str(tmp_path / "lessons.json"))
        analyzer.analyze("int-1", CONVERSATION_DEBUGGING)
        relevant = analyzer.consult_before_task("Call the checkout API with this tool")
        assert len(relevant) >= 1
        assert all(not lsn.resolved for lsn in relevant)
        assert all(lsn.lesson_text for lsn in relevant)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestReflectionConfig:
    def test_default_model_and_base_url(self):
        analyzer = ReflectionAnalyzer()
        assert analyzer.llm_model == "qwen3.5-9b"
        assert analyzer.llm_base_url == "http://localhost:11434"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:31b")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.0.0.5:11434")
        analyzer = ReflectionAnalyzer()
        assert analyzer.llm_model == "gemma4:31b"
        assert analyzer.llm_base_url == "http://10.0.0.5:11434"

    def test_explicit_args_beat_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:31b")
        analyzer = ReflectionAnalyzer(llm_model="custom-model", llm_base_url="http://x:1")
        assert analyzer.llm_model == "custom-model"
        assert analyzer.llm_base_url == "http://x:1"


# ---------------------------------------------------------------------------
# Prompt sanity
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_system_prompt_documents_schema(self):
        for key in ("went_well", "went_wrong", "missing_info", "lessons", "category", "severity"):
            assert key in _REFLECT_SYSTEM_PROMPT

    def test_user_prompt_renders_conversation(self):
        rendered = _render_conversation(CONVERSATION_DEBUGGING)
        assert "user" in rendered
        assert "/v1/checkout" in rendered
        filled = _REFLECT_USER_PROMPT.format(conversation=rendered)
        assert "/v1/checkout" in filled

    def test_render_conversation_truncates_and_skips_junk(self):
        conversation = [
            {"role": "user", "content": "x" * 10000},
            {"role": "assistant", "content": ""},
            "not-a-dict",
            {"role": "assistant", "content": "second message"},
        ]
        rendered = _render_conversation(conversation, max_chars=100)
        assert "second message" not in rendered  # truncated before it
        assert "(truncated)" in rendered
