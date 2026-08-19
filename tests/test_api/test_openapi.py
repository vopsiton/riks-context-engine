"""Tests for OpenAPI spec exposure (#123).

Verifies GET /openapi.json + GET /docs (Swagger UI) are served without
auth/tenant middleware interference, that every /api/v1/* endpoint appears
in the spec, and that example payloads are attached.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api.server import app

EXPECTED_PATHS = [
    "/health",
    "/models",
    "/api/chat",
    "/api/v1/context/messages",
    "/api/v1/context/summary",
    "/api/v1/memory/export",
    "/api/v1/memory/import",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def spec(client: TestClient):
    res = client.get("/openapi.json")
    assert res.status_code == 200
    return res.json()


class TestSpecExposure:
    def test_openapi_json_served_without_auth(self, client: TestClient):
        """/openapi.json must be reachable without API key or tenant header."""
        res = client.get("/openapi.json")
        assert res.status_code == 200
        assert res.json()["openapi"].startswith("3.")

    def test_docs_swagger_ui_served(self, client: TestClient):
        res = client.get("/docs")
        assert res.status_code == 200
        assert "swagger" in res.text.lower()

    def test_redoc_served(self, client: TestClient):
        res = client.get("/redoc")
        assert res.status_code == 200

    def test_spec_metadata(self, spec):
        assert spec["info"]["title"] == "Rik's Context Engine API"
        assert spec["info"]["version"]


class TestEndpointCoverage:
    def test_all_v1_endpoints_in_spec(self, spec):
        for path in EXPECTED_PATHS:
            assert path in spec["paths"], f"{path} missing from OpenAPI spec"

    def test_context_messages_has_get_and_post(self, spec):
        ops = spec["paths"]["/api/v1/context/messages"]
        assert "get" in ops and "post" in ops

    def test_endpoints_have_response_schemas(self, spec):
        """Every v1 endpoint must expose a 200 response schema."""
        for path in EXPECTED_PATHS:
            for verb, op in spec["paths"][path].items():
                if verb not in {"get", "post"}:
                    continue
                assert "200" in op.get("responses", {}), f"{verb.upper()} {path}: no 200 schema"

    def test_post_endpoints_have_request_schemas(self, spec):
        for path in ("/api/v1/context/messages", "/api/v1/memory/import", "/api/chat"):
            op = spec["paths"][path]["post"]
            schema = op["requestBody"]["content"]["application/json"]["schema"]
            assert schema, f"POST {path}: no request schema"


class TestExamples:
    def test_context_add_example(self, spec):
        ex = spec["paths"]["/api/v1/context/messages"]["post"]["requestBody"]["content"][
            "application/json"
        ]["examples"]["default"]["value"]
        assert ex["role"] == "user"
        assert "content" in ex

    def test_context_summary_example(self, spec):
        ex = spec["paths"]["/api/v1/context/summary"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["examples"]["default"]["value"]
        assert ex["messages_count"] == 7

    def test_memory_import_example(self, spec):
        ex = spec["paths"]["/api/v1/memory/import"]["post"]["requestBody"]["content"][
            "application/json"
        ]["examples"]["default"]["value"]
        assert ex["format"] == "json"

    def test_endpoints_are_tagged(self, spec):
        """Tags group the spec for discoverability (health/models/chat/context/memory)."""
        tags = {
            t
            for p in spec["paths"].values()
            for o in p.values()
            if isinstance(o, dict)
            for t in (o.get("tags") or [])
        }
        assert {"context", "memory"} <= tags


class TestSpecServedThroughMiddleware:
    def test_openapi_json_behind_middleware_stack(self, client: TestClient):
        """Spec must be served even with the full middleware stack active
        (rate limiting off, API key unset, tenant header absent)."""
        res = client.get("/openapi.json", headers={"X-Tenant-Id": ""})
        assert res.status_code == 200
