"""Integration tests for the performance monitoring endpoint (#103, OTel #109).

Covers:
- GET /health -> 200 + {"status": "ok"}.
- GET /metrics -> Prometheus text format with OTel-backed metric names
  (riks_request_count, riks_request_duration_seconds, riks_error_count).
- Metrics are fed by the audit middleware on every request via OTel.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.audit_log import reset_registry
from riks_context_engine.api.server import app
from riks_context_engine.api.telemetry import reset_metrics, reset_telemetry, setup_telemetry


@pytest.fixture(autouse=True)
def _reset_metrics_state():
    reset_telemetry()
    setup_telemetry()
    reset_metrics()
    reset_registry()
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    yield
    reset_metrics()
    reset_registry()
    reset_telemetry()


@pytest.fixture
def client():
    """TestClient with a valid X-Tenant-Id (tenant middleware passes through)."""
    with TestClient(app, headers={"X-Tenant-Id": "test-tenant"}) as c:
        yield c


def _metrics_text(client: TestClient) -> str:
    res = client.get("/metrics")
    assert res.status_code == 200
    return res.text


class TestHealth:
    def test_health_ok(self, client: TestClient):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


class TestMetrics:
    def test_metrics_prometheus_format(self, client: TestClient):
        client.get("/health")
        res = client.get("/metrics")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        assert "version=0.0.4" in res.headers["content-type"]
        text = res.text
        assert "riks_request_count" in text
        assert "riks_request_duration_seconds" in text

    def test_request_count_increments(self, client: TestClient):
        client.get("/health")
        client.get("/models")
        text = _metrics_text(client)
        assert "riks_request_count_total" in text
        val = _parse_counter_from_text(text, "riks_request_count_total")
        assert val >= 1

    def test_duration_histogram_present(self, client: TestClient):
        client.get("/health")
        text = _metrics_text(client)
        assert "riks_request_duration_seconds" in text

    def test_error_count_zero_when_no_5xx(self, client: TestClient):
        client.get("/health")
        val = _parse_counter(client, "riks_error_count_total")
        assert val == 0

    def test_error_count_increments_on_500(self, client: TestClient):
        @app.get("/__test_500__")
        def _boom():
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=500, content={"detail": "boom"})

        client.get("/__test_500__")
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/__test_500__"
        ]
        val = _parse_counter(client, "riks_error_count_total")
        assert val >= 1


def _parse_counter(client: TestClient, name: str) -> int:
    return _parse_counter_from_text(_metrics_text(client), name)


def _parse_counter_from_text(text: str, name: str) -> int:
    """Parse an OTel-exported Prometheus counter value.

    OTel lines look like: ``riks_request_count_total{otel_scope_name="riks",...} 3.0``
    """
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        metric_name = line.split("{")[0].split()[0] if "{" in line else line.split()[0]
        if metric_name == name:
            return int(float(line.rstrip().rsplit(" ", 1)[-1]))
    return 0
