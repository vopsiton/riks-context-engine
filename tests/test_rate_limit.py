"""Test API rate limiting (#99)."""

import os
import time
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _fresh_log():
    from riks_context_engine.api.server import _rate_limit_log

    _rate_limit_log.clear()
    return _rate_limit_log


def _make_app_client(config):
    """Build a minimal app wired with the real RateLimitMiddleware."""
    from riks_context_engine.api.server import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, config=config)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ping")
    def ping():
        return {"pong": True}

    return TestClient(app)


def _strip_rate_limit_env(environ):
    return {k: v for k, v in environ.items() if not k.startswith("RATE_LIMIT_")}


class TestRateLimitConfig:
    """RateLimitConfig parsing."""

    def test_config_defaults(self):
        """Disabled by default; 100 req / 60s window; per-IP mode."""
        from riks_context_engine.api.server import (
            _RATE_LIMIT_REQUESTS,
            _RATE_LIMIT_WINDOW,
            RateLimitConfig,
        )

        assert _RATE_LIMIT_REQUESTS == 100
        assert _RATE_LIMIT_WINDOW == 60

        env = _strip_rate_limit_env(os.environ)
        with patch.dict("os.environ", env, clear=True):
            cfg = RateLimitConfig()
        assert cfg.enabled is False
        assert cfg.mode == "ip"
        assert cfg.max_requests == 100
        assert cfg.window_seconds == 60

    def test_config_enabled_and_mode(self):
        """Config parses enable flag, per-user mode, and window values."""
        from riks_context_engine.api.server import RateLimitConfig

        env = _strip_rate_limit_env(os.environ)
        env.update(
            {
                "RATE_LIMIT_ENABLED": "true",
                "RATE_LIMIT_MODE": "user",
                "RATE_LIMIT_REQUESTS": "10",
                "RATE_LIMIT_WINDOW": "30",
            }
        )
        with patch.dict("os.environ", env, clear=True):
            cfg = RateLimitConfig()
        assert cfg.enabled is True
        assert cfg.mode == "user"
        assert cfg.max_requests == 10
        assert cfg.window_seconds == 30

    def test_config_rejects_bad_mode(self):
        """Invalid mode falls back to per-IP."""
        from riks_context_engine.api.server import RateLimitConfig

        env = _strip_rate_limit_env(os.environ)
        env["RATE_LIMIT_MODE"] = "bogus"
        with patch.dict("os.environ", env, clear=True):
            assert RateLimitConfig().mode == "ip"

    def test_env_values_configurable(self):
        """Rate limit values are configurable via env vars."""
        from riks_context_engine.api.server import RateLimitConfig

        env = _strip_rate_limit_env(os.environ)
        env.update({"RATE_LIMIT_REQUESTS": "50", "RATE_LIMIT_WINDOW": "30"})
        with patch.dict("os.environ", env, clear=True):
            cfg = RateLimitConfig()
        assert cfg.max_requests == 50
        assert cfg.window_seconds == 30


class TestSlidingWindow:
    """Core sliding-window accounting."""

    def test_check_allows_under_limit(self):
        """Under the limit, requests should be allowed."""
        from riks_context_engine.api.server import _check_rate_limit

        _fresh_log()
        allowed, remaining, reset = _check_rate_limit("fresh-ip")
        assert allowed is True
        assert remaining >= 0
        assert reset == 60

    def test_check_decrements_remaining(self):
        """Each recorded request decrements remaining count."""
        from riks_context_engine.api.server import _check_rate_limit, _record_request

        _fresh_log()
        ip = "decrement-test-ip"
        allowed1, rem1, _ = _check_rate_limit(ip)
        _record_request(ip)
        allowed2, rem2, _ = _check_rate_limit(ip)

        assert allowed1 is True
        assert allowed2 is True
        assert rem2 < rem1

    def test_check_denies_at_limit(self):
        """At max_requests within the window, requests are denied."""
        from riks_context_engine.api.server import (
            _check_rate_limit,
            _rate_limit_log,
            _record_request,
        )

        _fresh_log()
        ip = "denied-test-ip"
        for _ in range(3):
            _record_request(ip)

        allowed, remaining, reset = _check_rate_limit(ip, max_requests=3, window=60)
        assert allowed is False
        assert remaining == 0
        assert reset >= 1

        # after the recorded window expires, the IP is allowed again
        now = time.time()
        _rate_limit_log.clear()
        _rate_limit_log[ip] = [now - 61, now - 60, now - 59]
        allowed, remaining, _ = _check_rate_limit(ip, max_requests=3, window=60)
        assert allowed is True

    def test_window_releases_after_expiry(self):
        """Requests older than the window drop out of the count."""
        from riks_context_engine.api.server import _check_rate_limit

        log = _fresh_log()
        ip = "sliding-test-ip"
        now = time.time()
        # 2 requests in the window; oldest one already expired
        log[ip] = [now - 15, now - 4, now - 1]

        # 2 requests inside the 10s window -> at limit, not over
        allowed, remaining, _ = _check_rate_limit(ip, max_requests=2, window=10)
        assert allowed is False
        assert remaining == 0

        # 3 requests inside -> still over
        log[ip] = [now - 4, now - 3, now - 1]
        allowed, remaining, _ = _check_rate_limit(ip, max_requests=2, window=10)
        assert allowed is False

        # and once the older entries slip out, the window releases
        log[ip] = [now - 40, now - 30, now - 25]
        allowed, remaining, _ = _check_rate_limit(ip, max_requests=2, window=10)
        assert allowed is True

    def test_record_request_appends(self):
        """_record_request adds an entry to the log."""
        from riks_context_engine.api.server import _record_request

        log = _fresh_log()
        ip = "record-test-ip"
        _record_request(ip)
        _record_request(ip)
        assert len(log[ip]) >= 2


class TestGetClientIp:
    """Client IP extraction."""

    def test_x_forwarded_for_parsed(self):
        """X-Forwarded-For header is parsed correctly."""
        from riks_context_engine.api.server import _get_client_ip

        mock_request = MagicMock()
        mock_request.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        mock_request.client = MagicMock(host="127.0.0.1")

        assert _get_client_ip(mock_request) == "1.2.3.4"

    def test_fallback_to_client_host(self):
        """Falls back to request.client.host."""
        from riks_context_engine.api.server import _get_client_ip

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock(host="192.168.1.1")

        assert _get_client_ip(mock_request) == "192.168.1.1"

    def test_no_client(self):
        """Handles missing client gracefully."""
        from riks_context_engine.api.server import _get_client_ip

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = None

        assert _get_client_ip(mock_request) == "unknown"


class TestRateLimitMiddleware:
    """End-to-end middleware behavior via TestClient."""

    def _client(self, **env_overrides):
        from riks_context_engine.api.server import RateLimitConfig

        _fresh_log()
        env = _strip_rate_limit_env(os.environ)
        env.update(env_overrides)
        with patch.dict("os.environ", env, clear=True):
            return _make_app_client(RateLimitConfig())

    def test_under_limit_returns_200_with_headers(self):
        """Under the limit: 200 + X-RateLimit-* headers."""
        client = self._client(RATE_LIMIT_ENABLED="true")
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "100"
        assert int(resp.headers["X-RateLimit-Remaining"]) < 100

    def test_limit_overflow_returns_429_with_retry_after(self):
        """Over the limit: 429 + Retry-After header."""
        client = self._client(RATE_LIMIT_ENABLED="true", RATE_LIMIT_REQUESTS="3")
        for _ in range(3):
            assert client.get("/ping").status_code == 200

        resp = client.get("/ping")
        assert resp.status_code == 429
        assert int(resp.headers["Retry-After"]) >= 1
        assert resp.headers["X-RateLimit-Limit"] == "3"
        assert resp.headers["X-RateLimit-Remaining"] == "0"

    def test_disabled_never_returns_429(self):
        """When disabled, no 429 and no rate-limit headers."""
        client = self._client(RATE_LIMIT_ENABLED="false", RATE_LIMIT_REQUESTS="2")
        for _ in range(5):
            resp = client.get("/ping")
            assert resp.status_code == 200
            assert "X-RateLimit-Limit" not in resp.headers

    def test_disabled_by_default(self):
        """No RATE_LIMIT_* env vars -> limiter off (master switch defaults false)."""
        client = self._client()
        for _ in range(5):
            assert client.get("/ping").status_code == 200

    def test_health_endpoint_excluded(self):
        """/health is never rate limited."""
        client = self._client(RATE_LIMIT_ENABLED="true", RATE_LIMIT_REQUESTS="1")
        client.get("/ping")  # exhaust the single allowed request
        for _ in range(3):
            assert client.get("/health").status_code == 200

    def test_per_user_mode_scopes_by_tenant(self):
        """In user mode, limits are per X-Tenant-Id, not per IP."""
        client = self._client(
            RATE_LIMIT_ENABLED="true",
            RATE_LIMIT_MODE="user",
            RATE_LIMIT_REQUESTS="2",
        )
        headers_a = {"X-Tenant-Id": "tenant-a"}
        headers_b = {"X-Tenant-Id": "tenant-b"}
        for _ in range(2):
            assert client.get("/ping", headers=headers_a).status_code == 200
        assert client.get("/ping", headers=headers_a).status_code == 429
        # tenant-b is unaffected
        assert client.get("/ping", headers=headers_b).status_code == 200

    def test_no_rate_limit_leak_after_disabled(self):
        """A disabled limiter records nothing; a later window is clean."""
        from riks_context_engine.api.server import _rate_limit_log

        client = self._client(RATE_LIMIT_ENABLED="false")
        client.get("/ping")
        assert _rate_limit_log == {}
