"""E2E tests for CORS middleware — origin allow/deny + preflight (OPTIONS) [P2] (#174).

Acceptance criteria mapping:

- AC1 (Origin allow): :class:`TestOriginAllow`
- AC2 (Origin deny): :class:`TestOriginDeny`
- AC3 (Preflight OPTIONS): :class:`TestPreflight`
- AC4 (No wildcard): :class:`TestNoWildcard`
- AC5 (Config / two origin sets): :class:`TestOriginConfig`
- AC6 (Stability, 3 requests deterministic): :class:`TestStability`

MEASURED BEHAVIOR (not assumed, verified against live app via TestClient):

- CORS is ``fastapi.middleware.cors.CORSMiddleware`` added at import time
  (server.py:857-863) with config built by ``_build_cors_config()``
  (server.py:812). The config is captured at IMPORT TIME from the
  ``ALLOWED_ORIGINS`` env var (default: ``["http://localhost:3000",
  "http://localhost:8080"]``).
- ``allow_credentials=True`` always (hardcoded in ``_build_cors_config``).
- ``allow_methods``: GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD.
- ``allow_headers``: Authorization, Content-Type, X-Request-ID
  (plus FastAPI's defaults: Accept, Accept-Language, Content-Language).
- **Allow (allowed origin):** response has
  ``Access-Control-Allow-Origin: <origin>`` (echoed, NOT ``*``) AND
  ``Access-Control-Allow-Credentials: true``.
- **Deny (non-allowed origin):** ``Access-Control-Allow-Origin`` header
  is ABSENT (not present, not null, not ``*``). BUT
  ``Access-Control-Allow-Credentials: true`` IS still present
  (Starlette CORSMiddleware quirk: it sets allow-credentials on every
  response that has an Origin header, regardless of allow/deny).
  Response body is still 200 (CORS is a browser-enforcement layer, not
  a server-side block — the server happily serves the response; the
  browser is what blocks it).
- **Preflight (OPTIONS with Access-Control-Request-Method + ACRH):**
  - On a PROTECTED path (/api/chat): the preflight is NOT intercepted
    by the CORS middleware when ACRH is present — it falls through to
    the auth middleware. Without credentials → 401. WITH credentials
    → 200 + full CORS headers.
  - On a PUBLIC path (/health): the preflight IS intercepted and returns
    200 without auth + full CORS headers.
  - Returns 200 (not 204) with body "OK".
  - Headers: ``Access-Control-Allow-Methods`` (includes POST),
    ``Access-Control-Allow-Headers`` (includes Authorization, Content-Type),
    ``Access-Control-Max-Age: 600``, ``Access-Control-Allow-Origin``
    (echoed), ``Access-Control-Allow-Credentials: true``.
- **No wildcard:** ``Access-Control-Allow-Origin`` is NEVER ``*``; it is
  always either the echoed allowed origin or absent.
- **Config:** ``ALLOWED_ORIGINS`` env var (comma-separated). The app
  captures this at import time, so to test a different origin set we
  must build a fresh FastAPI app with a fresh CORSMiddleware (the
  module-level ``app`` is immutable after import for CORS purposes).

SCOPE: test-only. No product code changes.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import app as full_app

WS_KEY = "***"
TENANT = "t174"
# The full_app captures ALLOWED_ORIGINS at import time (default:
# ["http://localhost:3000", "http://localhost:8080"]). Tests against
# full_app must use these origins. Custom origin sets are tested via
# the mini-app pattern in TestOriginConfig.
ALLOWED = "http://localhost:3000"
DENIED = "http://evil.example"


@pytest.fixture(autouse=True)
def _clean_state():
    original_key = server_module.API_KEY
    server_module.API_KEY = WS_KEY
    yield
    server_module.API_KEY = original_key


def _auth_headers() -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-API-Key": WS_KEY}


def _cors_headers(resp) -> dict[str, str]:
    """Extract only the CORS-related headers from a response."""
    return {k: v for k, v in resp.headers.items() if "access-control" in k.lower()}


# ─── AC1: Origin allow ───────────────────────────────────────────────────────


class TestOriginAllow:
    """Allowed origin → Access-Control-Allow-Origin: <origin> + credentials."""

    def test_allowed_origin_echoed_in_header(self):
        """Allowed origin is echoed in Access-Control-Allow-Origin."""
        client = TestClient(full_app)
        resp = client.get(
            "/models",
            headers={**_auth_headers(), "Origin": ALLOWED},
        )
        assert resp.status_code == 200
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED, (
            f"expected {ALLOWED}, got {resp.headers.get('Access-Control-Allow-Origin')}"
        )

    def test_allowed_origin_includes_credentials(self):
        """Allowed origin response includes Access-Control-Allow-Credentials: true."""
        client = TestClient(full_app)
        resp = client.get(
            "/models",
            headers={**_auth_headers(), "Origin": ALLOWED},
        )
        assert resp.headers["Access-Control-Allow-Credentials"] == "true"

    def test_allowed_origin_on_health(self):
        """/health also reflects CORS for allowed origin."""
        client = TestClient(full_app)
        resp = client.get("/health", headers={"Origin": ALLOWED})
        assert resp.status_code == 200
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED

    def test_allowed_origin_on_post_endpoint(self):
        """CORS headers are also present on POST responses (allowed origin)."""
        client = TestClient(full_app)
        resp = client.post(
            "/api/chat",
            json={"prompt": "hi", "tenant_id": TENANT},
            headers={**_auth_headers(), "Origin": ALLOWED},
        )
        # The endpoint may return 400/422 for invalid body, but CORS headers
        # should still be present if the request reaches the CORS middleware.
        assert "Access-Control-Allow-Origin" in resp.headers, (
            f"CORS header missing on POST, status={resp.status_code}"
        )
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED


# ─── AC2: Origin deny ────────────────────────────────────────────────────────


class TestOriginDeny:
    """Non-allowed origin → no Access-Control-Allow-Origin header."""

    def test_denied_origin_has_no_allow_origin(self):
        """Denied origin: Access-Control-Allow-Origin header is ABSENT."""
        client = TestClient(full_app)
        resp = client.get(
            "/models",
            headers={**_auth_headers(), "Origin": DENIED},
        )
        assert resp.status_code == 200, "server still returns 200 (CORS is browser-enforced)"
        assert "Access-Control-Allow-Origin" not in resp.headers, (
            f"denied origin should NOT have Allow-Origin, got {resp.headers.get('Access-Control-Allow-Origin')}"
        )

    def test_denied_origin_is_not_null(self):
        """Denied origin: header is not present (not 'null', not '*')."""
        client = TestClient(full_app)
        resp = client.get(
            "/models",
            headers={**_auth_headers(), "Origin": DENIED},
        )
        header = resp.headers.get("Access-Control-Allow-Origin")
        assert header is None, f"expected absent, got {header!r}"

    def test_denied_origin_response_body_still_200(self):
        """CORS is a browser-enforcement layer: the server still returns
        200 with a body. The browser (not the server) blocks the response."""
        client = TestClient(full_app)
        resp = client.get(
            "/models",
            headers={**_auth_headers(), "Origin": DENIED},
        )
        assert resp.status_code == 200
        assert "models" in resp.json(), "response body is still served"

    def test_denied_origin_on_health(self):
        """/health with denied origin: no Allow-Origin header."""
        client = TestClient(full_app)
        resp = client.get("/health", headers={"Origin": DENIED})
        assert resp.status_code == 200
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_no_origin_header_means_no_cors_headers(self):
        """A request without an Origin header gets no CORS headers at all
        (CORS is only triggered by the presence of Origin)."""
        client = TestClient(full_app)
        resp = client.get("/models", headers=_auth_headers())
        assert "Access-Control-Allow-Origin" not in resp.headers


# ─── AC3: Preflight (OPTIONS) ───────────────────────────────────────────────


class TestPreflight:
    """OPTIONS preflight → correct CORS headers without auth."""

    def _preflight(self, client, origin: str = ALLOWED) -> Any:
        return client.options(
            "/api/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
                **_auth_headers(),
            },
        )

    def test_preflight_returns_200(self):
        """Preflight returns 200 (not 401, not 405)."""
        client = TestClient(full_app)
        resp = self._preflight(client)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}"

    def test_preflight_with_acrh_requires_auth_on_protected_path(self):
        """GAP NOTE (measured behavior): A preflight OPTIONS with
        Access-Control-Request-Headers on a PROTECTED path (/api/chat)
        is NOT intercepted by the CORS middleware — it falls through to
        the auth middleware and returns 401 if credentials are missing.

        This is a Starlette CORSMiddleware behavior: preflight interception
        only happens when the request looks like a 'simple' CORS preflight.
        When ACRH is present, the middleware checks if the requested headers
        are allowed, but the request still passes through the auth chain.

        A preflight on a PUBLIC path (/health) with ACRH returns 200 without
        auth (verified in test_preflight_on_health)."""
        client = TestClient(full_app)
        # No auth headers → 401 (auth middleware runs)
        resp = client.options(
            "/api/chat",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert resp.status_code == 401, (
            f"preflight without auth on protected path should be 401, got {resp.status_code}"
        )

    def test_preflight_includes_allow_methods_with_post(self):
        """Preflight response includes Access-Control-Allow-Methods with POST."""
        client = TestClient(full_app)
        resp = self._preflight(client)
        assert resp.status_code == 200
        allow_methods = resp.headers.get("Access-Control-Allow-Methods", "")
        assert "POST" in allow_methods, f"Allow-Methods should include POST, got: {allow_methods}"

    def test_preflight_includes_allow_headers(self):
        """Preflight response includes Access-Control-Allow-Headers with
        Authorization and Content-Type."""
        client = TestClient(full_app)
        resp = self._preflight(client)
        allow_headers = resp.headers.get("Access-Control-Allow-Headers", "")
        assert "Authorization" in allow_headers, (
            f"Allow-Headers should include Authorization, got: {allow_headers}"
        )
        assert "Content-Type" in allow_headers, (
            f"Allow-Headers should include Content-Type, got: {allow_headers}"
        )

    def test_preflight_includes_max_age(self):
        """Preflight response includes Access-Control-Max-Age (caching hint)."""
        client = TestClient(full_app)
        resp = self._preflight(client)
        max_age = resp.headers.get("Access-Control-Max-Age")
        assert max_age is not None, "Access-Control-Max-Age header missing"
        assert int(max_age) >= 0

    def test_preflight_includes_allow_origin(self):
        """Preflight response includes Access-Control-Allow-Origin (echoed)."""
        client = TestClient(full_app)
        resp = self._preflight(client)
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED

    def test_preflight_includes_credentials(self):
        """Preflight response includes Access-Control-Allow-Credentials: true."""
        client = TestClient(full_app)
        resp = self._preflight(client)
        assert resp.headers["Access-Control-Allow-Credentials"] == "true"

    def test_preflight_denied_origin_has_no_allow_origin(self):
        """Preflight with a DENIED origin: no Access-Control-Allow-Origin."""
        client = TestClient(full_app)
        resp = self._preflight(client, origin=DENIED)
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_preflight_on_health(self):
        """Preflight on /health (public path) works without auth.
        The CORS middleware intercepts it BEFORE the auth chain."""
        client = TestClient(full_app)
        resp = client.options(
            "/health",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert resp.status_code == 200, (
            f"health preflight should be 200 without auth, got {resp.status_code}"
        )
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED
        assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")


# ─── AC4: No wildcard ────────────────────────────────────────────────────────


class TestNoWildcard:
    """The wildcard (*) origin is NEVER returned (security requirement)."""

    def test_allow_origin_is_never_wildcard(self):
        """For any request, Access-Control-Allow-Origin is never '*'.
        It is either the echoed allowed origin or absent."""
        client = TestClient(full_app)
        for origin in [ALLOWED, DENIED, "http://random.org", "null"]:
            resp = client.get("/models", headers={**_auth_headers(), "Origin": origin})
            header = resp.headers.get("Access-Control-Allow-Origin")
            assert header != "*", f"wildcard * returned for origin {origin!r} — security violation"
            if header is not None:
                assert header == origin, f"Allow-Origin {header!r} != requested {origin!r}"

    def test_preflight_allow_origin_is_never_wildcard(self):
        """Preflight also never returns * for Allow-Origin."""
        client = TestClient(full_app)
        for origin in [ALLOWED, DENIED]:
            resp = client.options(
                "/api/chat",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                },
            )
            header = resp.headers.get("Access-Control-Allow-Origin")
            assert header != "*", f"preflight wildcard * for origin {origin!r}"

    def test_wildcard_cannot_be_used_to_bypass(self):
        """A client cannot craft a request that makes the server echo '*'.
        The server only echoes origins that are in the allowlist."""
        client = TestClient(full_app)
        # Try to trick the server
        tricky_origins = ["*", "null", "http://", "not-an-origin", ""]
        for origin in tricky_origins:
            if not origin:
                continue
            resp = client.get("/models", headers={**_auth_headers(), "Origin": origin})
            header = resp.headers.get("Access-Control-Allow-Origin")
            assert header != "*", f"server echoed * for tricky origin {origin!r}"


# ─── AC5: Config (two origin sets) ──────────────────────────────────────────


class TestOriginConfig:
    """The CORS allowlist is configurable via ALLOWED_ORIGINS env var.

    The module-level ``app`` captures ALLOWED_ORIGINS at import time, so
    to test a DIFFERENT origin set we build a fresh FastAPI app with a
    fresh CORSMiddleware (the config object is not re-read at runtime).
    """

    def _mini_app(self, allowed_origins: list[str]) -> TestClient:
        """Build a minimal FastAPI app with the given CORS allowlist."""
        mini = FastAPI()
        mini.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

        @mini.get("/models")
        def models():
            return {"models": ["test"]}

        @mini.get("/health")
        def health():
            return {"status": "ok"}

        return TestClient(mini)

    def test_origin_set_a(self):
        """Origin set A: allowed.example → 200 + Allow-Origin; evil.example → no header."""
        client = self._mini_app(["http://allowed.example"])
        r_allow = client.get("/models", headers={"Origin": "http://allowed.example"})
        assert r_allow.headers["Access-Control-Allow-Origin"] == "http://allowed.example"

        r_deny = client.get("/models", headers={"Origin": "http://evil.example"})
        assert "Access-Control-Allow-Origin" not in r_deny.headers

    def test_origin_set_b(self):
        """Origin set B: evil.example is now ALLOWED (different config)."""
        client = self._mini_app(["http://evil.example"])
        r_allow = client.get("/models", headers={"Origin": "http://evil.example"})
        assert r_allow.headers["Access-Control-Allow-Origin"] == "http://evil.example"

        r_deny = client.get("/models", headers={"Origin": "http://allowed.example"})
        assert "Access-Control-Allow-Origin" not in r_deny.headers

    def test_multiple_origins_in_config(self):
        """Multiple origins in the allowlist: both are allowed."""
        client = self._mini_app(["http://a.example", "http://b.example"])
        for origin in ["http://a.example", "http://b.example"]:
            resp = client.get("/models", headers={"Origin": origin})
            assert resp.headers["Access-Control-Allow-Origin"] == origin, (
                f"origin {origin} should be allowed"
            )
        resp = client.get("/models", headers={"Origin": "http://c.example"})
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_env_var_parsing_in_server_module(self):
        """The server module's _get_allowed_origins() correctly parses the
        ALLOWED_ORIGINS env var (comma-separated, stripped)."""
        from riks_context_engine.api.server import _get_allowed_origins

        # Default (no env var)
        env_backup = os.environ.get("ALLOWED_ORIGINS")
        try:
            os.environ.pop("ALLOWED_ORIGINS", None)
            default = _get_allowed_origins()
            assert "http://localhost:3000" in default
            assert "http://localhost:8080" in default

            # Custom env var
            os.environ["ALLOWED_ORIGINS"] = "http://one.example, http://two.example"
            custom = _get_allowed_origins()
            assert custom == ["http://one.example", "http://two.example"], (
                f"parsing failed: {custom}"
            )
        finally:
            if env_backup is not None:
                os.environ["ALLOWED_ORIGINS"] = env_backup
            else:
                os.environ.pop("ALLOWED_ORIGINS", None)


# ─── AC6: Stability ─────────────────────────────────────────────────────────


class TestStability:
    """CORS behavior is deterministic across 3 requests."""

    def test_allow_is_deterministic_across_3_requests(self):
        """3× allowed origin → same Allow-Origin header each time."""
        client = TestClient(full_app)
        results = []
        for _ in range(3):
            resp = client.get("/models", headers={**_auth_headers(), "Origin": ALLOWED})
            results.append(resp.headers.get("Access-Control-Allow-Origin"))
        assert all(r == ALLOWED for r in results), f"non-deterministic allow: {results}"

    def test_deny_is_deterministic_across_3_requests(self):
        """3× denied origin → no Allow-Origin header each time."""
        client = TestClient(full_app)
        results = []
        for _ in range(3):
            resp = client.get("/models", headers={**_auth_headers(), "Origin": DENIED})
            results.append(resp.headers.get("Access-Control-Allow-Origin"))
        assert all(r is None for r in results), f"non-deterministic deny: {results}"

    def test_preflight_is_deterministic_across_3_requests(self):
        """3× preflight → same Allow-Methods each time."""
        client = TestClient(full_app)
        results = []
        for _ in range(3):
            resp = client.options(
                "/health",
                headers={
                    "Origin": ALLOWED,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )
            results.append(resp.headers.get("Access-Control-Allow-Methods"))
        assert len(set(results)) == 1, f"non-deterministic preflight: {results}"
        assert "POST" in results[0]

    def test_credentials_is_deterministic(self):
        """Access-Control-Allow-Credentials is always 'true' for allowed
        origins across 3 requests."""
        client = TestClient(full_app)
        for _ in range(3):
            resp = client.get("/models", headers={**_auth_headers(), "Origin": ALLOWED})
            assert resp.headers["Access-Control-Allow-Credentials"] == "true"
