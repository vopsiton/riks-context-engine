"""OpenTelemetry bootstrap — traces + OTel-backed Prometheus metrics (#109)."""

from __future__ import annotations

import logging
import os

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Tracer

_setup_done = False
_prometheus_reader: MetricReader | None = None


def _otel_enabled() -> bool:
    return os.environ.get("RIKS_OTEL_ENABLED", "1").strip() not in ("0", "false", "no")


def setup_telemetry(service_name: str = "riks-context-engine") -> None:
    """Initialise OTel TracerProvider + MeterProvider + PrometheusMetricReader.

    Safe to call more than once (idempotent). When ``RIKS_OTEL_ENABLED=0``
    the global providers are left as NoOp — zero overhead.
    """
    global _setup_done, _prometheus_reader

    if _setup_done:
        return
    _setup_done = True

    if not _otel_enabled():
        return

    resource = Resource.create({"service.name": service_name})

    import sys

    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    trace.set_tracer_provider(tracer_provider)

    try:
        from opentelemetry.exporter.prometheus import PrometheusMetricReader

        _prometheus_reader = PrometheusMetricReader()
        meter_provider = MeterProvider(resource=resource, metric_readers=[_prometheus_reader])
        otel_metrics.set_meter_provider(meter_provider)
    except ImportError:
        # opentelemetry-exporter-prometheus is optional; skip the metrics
        # reader if it is not installed (tests, minimal environments).
        logging.getLogger(__name__).debug(
            "opentelemetry-exporter-prometheus not installed; Prometheus metrics disabled."
        )


def reset_telemetry() -> None:
    """Reset global state so ``setup_telemetry`` can be called again (tests only)."""
    global _setup_done, _prometheus_reader
    _setup_done = False
    _prometheus_reader = None

    import opentelemetry.metrics._internal as _mi
    import opentelemetry.trace as _t

    _t._TRACER_PROVIDER_SET_ONCE = _t.Once()
    _t._TRACER_PROVIDER = None

    _mi._METER_PROVIDER_SET_ONCE = _mi.Once()
    _mi._METER_PROVIDER = None

    import prometheus_client

    collectors = list(prometheus_client.REGISTRY._names_to_collectors.values())
    for c in collectors:
        try:
            prometheus_client.REGISTRY.unregister(c)
        except Exception:
            pass

    reset_metrics()


def get_tracer(name: str = "riks") -> Tracer:
    return trace.get_tracer(name)


def get_meter(name: str = "riks") -> Meter:
    return otel_metrics.get_meter(name)


def get_prometheus_output() -> str:
    """Return Prometheus text exposition from the in-process reader."""
    if _prometheus_reader is None:
        return ""
    from typing import Any

    from prometheus_client import generate_latest

    raw: Any = generate_latest()
    text: str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    return text


# --- Convenience metric accessors (created lazily, cached) ---

_request_counter: Counter | None = None
_error_counter: Counter | None = None
_duration_histogram: Histogram | None = None


def _ensure_metrics() -> None:
    global _request_counter, _error_counter, _duration_histogram
    if _request_counter is not None:
        return
    meter = get_meter()
    _request_counter = meter.create_counter(
        "riks_request_count",
        description="Total number of HTTP requests processed.",
    )
    _error_counter = meter.create_counter(
        "riks_error_count",
        description="Total number of HTTP requests that errored (status >= 500).",
    )
    _duration_histogram = meter.create_histogram(
        "riks_request_duration_seconds",
        description="HTTP request latency in seconds.",
        unit="s",
    )


def observe_request(duration_s: float, status: int) -> None:
    """Record one HTTP request in OTel metrics."""
    _ensure_metrics()
    assert _request_counter is not None
    assert _duration_histogram is not None
    assert _error_counter is not None
    _request_counter.add(1)
    _duration_histogram.record(duration_s)
    if status >= 500:
        _error_counter.add(1)


def reset_metrics() -> None:
    """Reset cached metric instruments (test helper)."""
    global _request_counter, _error_counter, _duration_histogram
    _request_counter = None
    _error_counter = None
    _duration_histogram = None
