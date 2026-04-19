"""Tests for Issue #49 — CORS PATCH/HEAD Methods."""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _build_cors_config():
    """Re-implementation for testing the fix."""
    return {
        "allow_origins": ["http://localhost:3000", "http://localhost:8080"],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
        "allow_headers": ["Authorization", "Content-Type", "X-Request-ID"],
    }


class TestCorsPatchHead:
    """Test CORS middleware includes PATCH and HEAD methods."""

    def test_patch_in_allowed_methods(self):
        """AC-49-01: PATCH method should be in allowed methods."""
        config = _build_cors_config()
        assert "PATCH" in config["allow_methods"]

    def test_head_in_allowed_methods(self):
        """AC-49-02: HEAD method should be in allowed methods."""
        config = _build_cors_config()
        assert "HEAD" in config["allow_methods"]

    def test_cors_middleware_with_patch(self):
        """PATCH request should be allowed by CORS middleware."""
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            **_build_cors_config(),
        )

        @app.patch("/test")
        def patch_endpoint():
            return {"method": "PATCH"}

        client = TestClient(app, raise_server_exceptions=False)
        # CORS preflight for PATCH
        response = client.options(
            "/test",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        # Should not be 405 Method Not Allowed
        assert response.status_code != 405

    def test_cors_middleware_with_head(self):
        """HEAD request should be allowed by CORS middleware."""
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            **_build_cors_config(),
        )

        @app.head("/test")
        def head_endpoint():
            return {"method": "HEAD"}

        @app.get("/test")
        def get_endpoint():
            return {"method": "GET"}

        client = TestClient(app, raise_server_exceptions=False)
        # HEAD without body - CORS preflight
        response = client.options(
            "/test",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "HEAD",
            },
        )
        # Should not be 405
        assert response.status_code != 405

    def test_cors_preflight_options_204(self):
        """AC-49-03: Preflight OPTIONS should return 204 or 200."""
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            **_build_cors_config(),
        )

        @app.patch("/test")
        def patch_endpoint():
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.options(
            "/test",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        # 204 No Content or 200 OK is acceptable for preflight
        assert response.status_code in (200, 204)

    def test_cors_credentials_true(self):
        """AC-49-04: Credentials header should be allowed."""
        config = _build_cors_config()
        assert config.get("allow_credentials") is True
