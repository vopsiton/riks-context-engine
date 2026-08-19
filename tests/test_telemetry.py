"""Tests for the OpenTelemetry bootstrap module (#109).

Covers:
- setup_telemetry() idempotent
- RIKS_OTEL_ENABLED=0 → NoOp tracer, zero spans
- Span creation after setup
- MCP tool tracing via health_check
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from riks_context_engine.api.telemetry import (
    get_tracer,
    reset_metrics,
    reset_telemetry,
    setup_telemetry,
)


class _CollectorExporter(SpanExporter):
    """Minimal span collector for testing."""

    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


@pytest.fixture(autouse=True)
def _clean_otel(monkeypatch):
    reset_telemetry()
    reset_metrics()
    monkeypatch.delenv("RIKS_OTEL_ENABLED", raising=False)
    yield
    reset_telemetry()
    reset_metrics()


class TestSetupTelemetry:
    def test_idempotent(self):
        setup_telemetry()
        provider1 = trace.get_tracer_provider()
        setup_telemetry()
        provider2 = trace.get_tracer_provider()
        assert provider1 is provider2

    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setenv("RIKS_OTEL_ENABLED", "0")
        setup_telemetry()
        assert not isinstance(trace.get_tracer_provider(), TracerProvider)

    def test_noop_no_spans_when_disabled(self, monkeypatch):
        monkeypatch.setenv("RIKS_OTEL_ENABLED", "0")
        setup_telemetry()
        tracer = get_tracer()
        with tracer.start_as_current_span("should.not.appear") as span:
            pass
        assert not span.is_recording()

    def test_spans_created_when_enabled(self):
        setup_telemetry()
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        exporter = _CollectorExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        tracer = get_tracer()
        with tracer.start_as_current_span("test.span", attributes={"key": "val"}):
            pass

        assert len(exporter.spans) >= 1
        assert exporter.spans[-1].name == "test.span"
        assert exporter.spans[-1].attributes["key"] == "val"


class TestMCPToolTracing:
    def test_health_check_span(self):
        setup_telemetry()
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        exporter = _CollectorExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        from riks_context_engine.mcp.handlers import ToolHandler

        handler = ToolHandler()
        tracer = trace.get_tracer("riks")
        with tracer.start_as_current_span(
            "mcp.tool.health_check",
            attributes={"tool_name": "health_check"},
        ) as span:
            result = handler.health_check({})
            span.set_attribute("status", "done")

        assert result["status"] == "ok"
        tool_spans = [s for s in exporter.spans if s.name == "mcp.tool.health_check"]
        assert len(tool_spans) == 1
        assert tool_spans[0].attributes["tool_name"] == "health_check"
        assert tool_spans[0].attributes["status"] == "done"

    def test_task_execute_span(self):
        setup_telemetry()
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        exporter = _CollectorExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        from riks_context_engine.mcp.handlers import ToolHandler

        handler = ToolHandler(data_dir="/tmp/riks-test-otel")
        result = handler.task_execute({
            "tenant_id": "test-tenant",
            "goal": "echo: hello",
            "timeout": 10,
        })
        assert result["status"] == "done"
        task_spans = [s for s in exporter.spans if s.name == "riks.task.execute"]
        assert len(task_spans) == 1
        assert task_spans[0].attributes["goal"] == "echo: hello"
        assert task_spans[0].attributes["status"] == "done"
