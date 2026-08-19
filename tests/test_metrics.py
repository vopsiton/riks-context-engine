"""Integration tests for the performance monitoring endpoint (#103).

Covers:
- GET /health -> 200 + {"status": "ok"}.
- GET /metrics -> Prometheus text format with the expected metric names
  (riks_request_count, riks_request_duration_seconds, riks_error_count).
- Metrics are fed by the audit middleware on every request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.audit_log import reset_metrics, reset_registry
from riks_context_engine.api.server import app


@pytest.fixture(autouse=True)
def _reset_metrics_state():
    reset_metrics()
    reset_registry()
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    yield
    reset_metrics()
    reset_registry()


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
        # Criterion (a): /health -> 200 + {"status": "ok"}.
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


class TestMetrics:
    def test_metrics_prometheus_format(self, client: TestClient):
        # Criterion (b): /metrics -> Prometheus text format with expected names.
        # A request (health) has been made; ensure the metrics reflect it.
        client.get("/health")
        res = client.get("/metrics")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        assert "version=0.0.4" in res.headers["content-type"]
        text = res.text
        # All three expected metric names are present.
        assert "riks_request_count" in text
        assert "riks_request_duration_seconds" in text
        assert "riks_error_count" in text
        # Prometheus structure: HELP + TYPE lines for each metric.
        assert "# HELP riks_request_count" in text
        assert "# TYPE riks_request_count counter" in text
        assert "# TYPE riks_request_duration_seconds histogram" in text
        assert "# TYPE riks_error_count counter" in text

    def test_request_count_increments(self, client: TestClient):
        # The audit middleware feeds riks_request_count on every request.
        before = _parse_counter(client, "riks_request_count")
        client.get("/health")
        client.get("/models")
        after = _parse_counter(client, "riks_request_count")
        assert after >= before + 2

    def test_duration_histogram_present(self, client: TestClient):
        client.get("/health")
        text = _metrics_text(client)
        # Histogram buckets include +Inf and _sum/_count series.
        assert 'riks_request_duration_seconds_bucket{le="+Inf"}' in text
        assert "riks_request_duration_seconds_sum" in text
        assert "riks_request_duration_seconds_count" in text

    def test_error_count_zero_when_no_5xx(self, client: TestClient):
        client.get("/health")
        text = _metrics_text(client)
        assert "riks_error_count 0" in text

    def test_error_count_increments_on_500(self, client: TestClient):
        # A 500 response must increment riks_error_count. We inject a handler
        # that returns 500 to exercise the error path without a real failure.
        @app.get("/__test_500__")
        def _boom():
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=500, content={"detail": "boom"})

        client.get("/__test_500__")
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/__test_500__"
        ]
        text = _metrics_text(client)
        assert "riks_error_count 1" in text


def _parse_counter(client: TestClient, name: str) -> int:
    text = _metrics_text(client)
    for line in text.splitlines():
        if line.startswith(name) and "{" not in line:
            return int(line.split()[-1])
    return 0
