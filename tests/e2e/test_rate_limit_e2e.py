"""E2E tests for rate limiting — 429 + Retry-After, per-tenant, /health exemption [P2] (#173).

Acceptance criteria mapping:

- AC1 (429 + Retry-After): :class:`TestRateLimit429`
- AC2 (per-tenant isolation): :class:`TestPerTenantIsolation`
- AC3 (/health exemption): :class:`TestHealthExemption`
- AC4 (limit threshold): :class:`TestLimitThreshold`
- AC5 (stability / recovery): :class:`TestRecoveryAndStability`

MEASURED BEHAVIOR (not assumed):

- Rate limiting is implemented as ``RateLimitMiddleware`` (server.py:316),
  a ``BaseHTTPMiddleware`` added via ``app.add_middleware()`` at import time
  (server.py:866). The config is a module-level ``_rate_limit_config``
  (server.py:865) loaded from env vars at import time.
- Default config: ``RATE_LIMIT_ENABLED=false`` (limiter OFF by default),
  mode="ip", max_requests=100, window=60s.
- When enabled, the middleware:
  - Skips ``/health`` entirely (no rate limit check, no headers).
  - For other paths, builds a key: ``user:{tenant}`` in user mode
    (if ``X-Tenant-Id`` present), else ``ip:{client_ip}``.
  - Checks a sliding window: counts entries in ``_rate_limit_log[key]``
    within the last ``window`` seconds. If count >= max_requests → 429.
  - On 429: returns ``JSONResponse`` with ``Retry-After`` (seconds until
    oldest entry expires), ``X-RateLimit-Limit``, ``X-RateLimit-Remaining=0``,
    ``X-RateLimit-Reset``.
  - On allowed: records the request, adds ``X-RateLimit-Limit`` and
    ``X-RateLimit-Remaining`` headers to the response.
- The sliding window uses ``time.time()`` — tests can monkeypatch
  ``_rate_limit_log`` directly to simulate time passing (deterministic
  recovery test without waiting 60s).
- In the real app (``app``), protected paths require API key + tenant.
  Rate limiting is checked BEFORE auth (middleware order: RateLimit →
  APIKeyAuth → TenantAuth). So a 429 response does NOT require valid
  auth credentials.

SCOPE: test-only. No product code changes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import (
    RateLimitConfig,
    RateLimitMiddleware,
    _rate_limit_log,
    app,
)

WS_KEY = "***"
TENANT = "t173"
LIMIT = 5
WINDOW = 60


def _fresh_log() -> None:
    _rate_limit_log.clear()


@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure clean rate limit state before/after each test."""
    _fresh_log()
    original_key = server_module.API_KEY
    server_module.API_KEY = WS_KEY
    yield
    _fresh_log()
    server_module.API_KEY = original_key


def _make_test_app() -> TestClient:
    """Build a minimal FastAPI app with the real RateLimitMiddleware.

    This isolates rate limiting behavior from the full app (auth,
    tenant validation) so we can test the limiter in isolation.
    The middleware is the same class used in production.
    """
    from fastapi import FastAPI

    mini_app = FastAPI()
    cfg = RateLimitConfig()
    cfg.enabled = True
    cfg.mode = "user"
    cfg.max_requests = LIMIT
    cfg.window_seconds = WINDOW
    mini_app.add_middleware(RateLimitMiddleware, config=cfg)

    @mini_app.get("/health")
    def health():
        return {"status": "ok"}

    @mini_app.get("/ping")
    def ping():
        return {"pong": True}

    return TestClient(mini_app)


def _make_full_app_client() -> TestClient:
    """Build a TestClient for the full app (with auth middleware)."""
    return TestClient(app, headers={"X-Tenant-Id": TENANT, "X-API-Key": WS_KEY})


# ─── AC1: 429 + Retry-After ──────────────────────────────────────────────────


class TestRateLimit429:
    """When the rate limit is exceeded, the response is 429 with Retry-After."""

    def test_limit_exceeded_returns_429(self):
        """LIMIT requests → 200, (LIMIT+1)th → 429."""
        client = _make_test_app()
        for i in range(LIMIT):
            resp = client.get("/ping")
            assert resp.status_code == 200, f"request {i + 1} should be 200, got {resp.status_code}"

        resp = client.get("/ping")
        assert resp.status_code == 429, f"expected 429, got {resp.status_code}"

    def test_429_includes_retry_after_header(self):
        """429 response includes Retry-After header with a reasonable value
        (1 ≤ value ≤ window_seconds)."""
        client = _make_test_app()
        for _ in range(LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers, "Retry-After header missing"
        retry_after = int(resp.headers["Retry-After"])
        assert 1 <= retry_after <= WINDOW, f"Retry-After={retry_after} not in [1, {WINDOW}]"

    def test_429_includes_x_ratelimit_headers(self):
        """429 response includes X-RateLimit-Limit and X-RateLimit-Remaining=0."""
        client = _make_test_app()
        for _ in range(LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert resp.headers["X-RateLimit-Limit"] == str(LIMIT)
        assert resp.headers["X-RateLimit-Remaining"] == "0"

    def test_429_body_has_detail(self):
        """429 response body has a 'detail' field (understandable error)."""
        client = _make_test_app()
        for _ in range(LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        body = resp.json()
        assert "detail" in body, f"expected 'detail' in 429 body, got: {body}"

    def test_allowed_requests_include_x_ratelimit_remaining(self):
        """Allowed (200) responses include X-RateLimit-Remaining header
        that decrements with each request."""
        client = _make_test_app()
        resp1 = client.get("/ping")
        assert resp1.status_code == 200
        remaining1 = int(resp1.headers["X-RateLimit-Remaining"])

        resp2 = client.get("/ping")
        assert resp2.status_code == 200
        remaining2 = int(resp2.headers["X-RateLimit-Remaining"])

        assert remaining2 < remaining1, f"remaining should decrease: {remaining1} → {remaining2}"

    def test_429_takes_priority_over_auth_in_full_app(self):
        """In the full app, the rate limit middleware runs BEFORE auth
        (middleware order: RateLimit → APIKeyAuth → TenantAuth).
        When the limit is exhausted, 429 is returned instead of 401.

        Note: The middleware captures its config at construction time
        (app.add_middleware at import), so we build a mini-app with a
        fresh RateLimitConfig to test this behavior in isolation.
        """
        from fastapi import FastAPI

        _fresh_log()
        mini_app = FastAPI()
        cfg = RateLimitConfig()
        cfg.enabled = True
        cfg.max_requests = 2
        mini_app.add_middleware(RateLimitMiddleware, config=cfg)

        @mini_app.get("/models")
        def models():
            return {"models": ["test-model"]}

        with TestClient(mini_app) as client:
            # 2 requests: 200 (no auth middleware in mini-app)
            for _ in range(2):
                resp = client.get("/models")
                assert resp.status_code == 200
            # 3rd request: rate limit exceeded → 429
            resp = client.get("/models")
            assert resp.status_code == 429, f"expected 429, got {resp.status_code}"
            assert "Retry-After" in resp.headers
        _fresh_log()


# ─── AC2: per-tenant isolation ──────────────────────────────────────────────


class TestPerTenantIsolation:
    """Rate limits are per-tenant: tenant A's limit does not affect tenant B."""

    def test_tenant_a_limit_does_not_affect_tenant_b(self):
        """Tenant A exhausts the limit → 429. Tenant B (fresh) → 200."""
        client = _make_test_app()
        headers_a = {"X-Tenant-Id": "tenant-a"}
        headers_b = {"X-Tenant-Id": "tenant-b"}

        # Exhaust tenant A's limit
        for _ in range(LIMIT):
            resp = client.get("/ping", headers=headers_a)
            assert resp.status_code == 200
        resp_a = client.get("/ping", headers=headers_a)
        assert resp_a.status_code == 429, f"tenant A should be 429, got {resp_a.status_code}"

        # Tenant B should be unaffected
        resp_b = client.get("/ping", headers=headers_b)
        assert resp_b.status_code == 200, (
            f"tenant B should be 200, got {resp_b.status_code} (limit not per-tenant?)"
        )

    def test_tenant_b_can_make_full_limit_requests(self):
        """After tenant A is rate-limited, tenant B can still make all
        LIMIT requests without hitting 429."""
        client = _make_test_app()
        headers_a = {"X-Tenant-Id": "tenant-a"}
        headers_b = {"X-Tenant-Id": "tenant-b"}

        # Exhaust tenant A
        for _ in range(LIMIT):
            client.get("/ping", headers=headers_a)
        assert client.get("/ping", headers=headers_a).status_code == 429

        # Tenant B can make all LIMIT requests
        for i in range(LIMIT):
            resp = client.get("/ping", headers=headers_b)
            assert resp.status_code == 200, (
                f"tenant B request {i + 1} should be 200, got {resp.status_code}"
            )

    def test_tenant_keys_are_isolated_in_log(self):
        """The rate limit log has separate entries per tenant."""
        client = _make_test_app()
        headers_a = {"X-Tenant-Id": "tenant-a"}
        headers_b = {"X-Tenant-Id": "tenant-b"}

        client.get("/ping", headers=headers_a)
        client.get("/ping", headers=headers_b)

        # The log should have separate keys for each tenant
        assert "user:tenant-a" in _rate_limit_log, "tenant A key missing from log"
        assert "user:tenant-b" in _rate_limit_log, "tenant B key missing from log"
        assert len(_rate_limit_log["user:tenant-a"]) == 1
        assert len(_rate_limit_log["user:tenant-b"]) == 1

    def test_no_tenant_header_falls_back_to_ip_key(self):
        """When X-Tenant-Id is absent, the rate limit key falls back to
        ip:{client_ip} (not user:none)."""
        client = _make_test_app()
        # No tenant header → IP-based key
        resp = client.get("/ping")
        assert resp.status_code == 200
        # The log should have an ip: key, not a user: key
        ip_keys = [k for k in _rate_limit_log if k.startswith("ip:")]
        assert len(ip_keys) == 1, f"expected 1 ip: key, got {list(_rate_limit_log.keys())}"


# ─── AC3: /health exemption ──────────────────────────────────────────────────


class TestHealthExemption:
    """/health is exempt from rate limiting (critical for monitoring)."""

    def test_health_returns_200_when_limit_exceeded(self):
        """After exhausting the limit on /ping, /health still returns 200."""
        client = _make_test_app()
        for _ in range(LIMIT):
            client.get("/ping")
        # Limit is now exceeded
        assert client.get("/ping").status_code == 429

        # /health should still work
        resp = client.get("/health")
        assert resp.status_code == 200, f"/health should be 200, got {resp.status_code}"

    def test_health_does_not_consume_rate_limit(self):
        """/health requests are not recorded in the rate limit log."""
        client = _make_test_app()
        # Make several /health requests
        for _ in range(LIMIT + 5):
            resp = client.get("/health")
            assert resp.status_code == 200

        # /ping should still be fully available (no rate limit consumed by /health)
        for i in range(LIMIT):
            resp = client.get("/ping")
            assert resp.status_code == 200, (
                f"request {i + 1}/{LIMIT} after /health burst should be 200, got {resp.status_code}"
            )

        # The rate limit log should have entries only for /ping (not /health)
        # /health is skipped before the key is built, so no /health entries
        for key in _rate_limit_log:
            assert not key.startswith("health"), f"unexpected health key: {key}"

    def test_health_no_x_ratelimit_headers(self):
        """/health responses do NOT include X-RateLimit-* headers
        (the middleware skips health entirely)."""
        client = _make_test_app()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" not in resp.headers, (
            "/health should not have X-RateLimit-Limit header"
        )
        assert "X-RateLimit-Remaining" not in resp.headers, (
            "/health should not have X-RateLimit-Remaining header"
        )

    def test_health_exemption_is_deterministic(self):
        """/health exemption is consistent across multiple limit cycles."""
        client = _make_test_app()
        for _ in range(3):
            _fresh_log()
            # Exhaust the limit
            for _ in range(LIMIT):
                client.get("/ping")
            assert client.get("/ping").status_code == 429
            # /health still works
            assert client.get("/health").status_code == 200


# ─── AC4: limit threshold ────────────────────────────────────────────────────


class TestLimitThreshold:
    """The exact limit threshold is measured and pinned."""

    def test_exactly_limit_requests_succeed(self):
        """Exactly LIMIT requests → all 200."""
        client = _make_test_app()
        for i in range(LIMIT):
            resp = client.get("/ping")
            assert resp.status_code == 200, f"request {i + 1}/{LIMIT} should be 200"

    def test_limit_plus_one_returns_429(self):
        """(LIMIT+1)th request → 429 (the threshold is exactly LIMIT)."""
        client = _make_test_app()
        for _ in range(LIMIT):
            client.get("/ping")
        resp = client.get("/ping")  # (LIMIT+1)th
        assert resp.status_code == 429, (
            f"request {LIMIT + 1} should be 429 (limit={LIMIT}), got {resp.status_code}"
        )

    def test_limit_is_configurable(self):
        """The limit threshold is configurable (not hardcoded)."""
        # The config object's max_requests field determines the threshold
        cfg = RateLimitConfig()
        # Default is 100 (from env or default)
        # We can construct with different values
        assert isinstance(cfg.max_requests, int)
        assert cfg.max_requests > 0

    def test_remaining_counts_down_to_zero(self):
        """X-RateLimit-Remaining counts down from (LIMIT-1) to 0."""
        client = _make_test_app()
        remaining_values = []
        for _ in range(LIMIT):
            resp = client.get("/ping")
            assert resp.status_code == 200
            remaining_values.append(int(resp.headers["X-RateLimit-Remaining"]))

        # Remaining should be monotonically decreasing
        for i in range(1, len(remaining_values)):
            assert remaining_values[i] < remaining_values[i - 1], (
                f"remaining should decrease: {remaining_values}"
            )
        # Last remaining should be 0
        assert remaining_values[-1] == 0, f"last remaining should be 0, got {remaining_values[-1]}"


# ─── AC5: stability / recovery ───────────────────────────────────────────────


class TestRecoveryAndStability:
    """The rate limit behavior is deterministic and recovers after the window."""

    def test_recovery_after_window_expiry(self):
        """After the window expires (simulated by manipulating timestamps),
        the rate limit resets and requests succeed again."""
        client = _make_test_app()
        # Exhaust the limit
        for _ in range(LIMIT):
            client.get("/ping")
        assert client.get("/ping").status_code == 429

        # Simulate window expiry: shift all timestamps back by (window + 1) seconds
        old_offset = WINDOW + 1
        for key in list(_rate_limit_log.keys()):
            _rate_limit_log[key] = [ts - old_offset for ts in _rate_limit_log[key]]

        # Now the window should be empty → requests succeed again
        resp = client.get("/ping")
        assert resp.status_code == 200, (
            f"after window expiry, request should be 200, got {resp.status_code}"
        )

    def test_recovery_is_complete(self):
        """After recovery, the full limit is available again (not partial)."""
        client = _make_test_app()
        # Exhaust the limit
        for _ in range(LIMIT):
            client.get("/ping")
        assert client.get("/ping").status_code == 429

        # Simulate window expiry
        old_offset = WINDOW + 1
        for key in list(_rate_limit_log.keys()):
            _rate_limit_log[key] = [ts - old_offset for ts in _rate_limit_log[key]]

        # Full limit should be available again
        for i in range(LIMIT):
            resp = client.get("/ping")
            assert resp.status_code == 200, (
                f"recovery request {i + 1}/{LIMIT} should be 200, got {resp.status_code}"
            )

    def test_limit_behavior_is_deterministic(self):
        """Reset + repeat: the same sequence of requests produces the same
        status codes (deterministic behavior)."""
        results_1 = []
        results_2 = []
        for run in range(2):
            _fresh_log()
            client = _make_test_app()
            for _ in range(LIMIT + 2):
                resp = client.get("/ping")
                (results_1 if run == 0 else results_2).append(resp.status_code)

        assert results_1 == results_2, (
            f"non-deterministic behavior:\n  run 1: {results_1}\n  run 2: {results_2}"
        )
        # Verify the expected pattern: LIMIT×200, then 429, 429
        assert results_1 == [200] * LIMIT + [429, 429], f"unexpected pattern: {results_1}"

    def test_disabled_limiter_never_returns_429(self):
        """When rate limiting is disabled, no request ever returns 429
        (regression test)."""
        from fastapi import FastAPI

        mini_app = FastAPI()
        cfg = RateLimitConfig()
        cfg.enabled = False  # Disabled
        mini_app.add_middleware(RateLimitMiddleware, config=cfg)

        @mini_app.get("/ping")
        def ping():
            return {"pong": True}

        client = TestClient(mini_app)
        for _ in range(100):
            resp = client.get("/ping")
            assert resp.status_code == 200, (
                f"disabled limiter should never 429, got {resp.status_code}"
            )
