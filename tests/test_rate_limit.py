"""Test API rate limiting."""

from unittest.mock import MagicMock, patch


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_rate_limit_config_defaults(self):
        """Default rate limit is 100 req/min."""
        from riks_context_engine.api.server import (
            _RATE_LIMIT_REQUESTS,
            _RATE_LIMIT_WINDOW,
        )

        assert _RATE_LIMIT_REQUESTS == 100
        assert _RATE_LIMIT_WINDOW == 60

    def test_check_rate_limit_allows_under_limit(self):
        """Under the limit, requests should be allowed."""
        from riks_context_engine.api.server import _check_rate_limit

        allowed, remaining, reset = _check_rate_limit("fresh-ip")
        assert allowed is True
        assert remaining >= 0
        assert reset == 60

    def test_check_rate_limit_decrements_remaining(self):
        """Each request decrements remaining count."""
        from riks_context_engine.api.server import _check_rate_limit, _record_request

        ip = "decrement-test-ip"
        allowed1, rem1, _ = _check_rate_limit(ip)
        _record_request(ip)
        allowed2, rem2, _ = _check_rate_limit(ip)

        assert rem2 < rem1

    def test_get_client_ip_from_x_forwarded(self):
        """X-Forwarded-For header is parsed correctly."""
        from riks_context_engine.api.server import _get_client_ip

        mock_request = MagicMock()
        mock_request.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        mock_request.client = MagicMock(host="127.0.0.1")

        ip = _get_client_ip(mock_request)
        assert ip == "1.2.3.4"

    def test_get_client_ip_fallback(self):
        """Falls back to request.client.host."""
        from riks_context_engine.api.server import _get_client_ip

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock(host="192.168.1.1")

        ip = _get_client_ip(mock_request)
        assert ip == "192.168.1.1"

    def test_get_client_ip_no_client(self):
        """Handles missing client gracefully."""
        from riks_context_engine.api.server import _get_client_ip

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = None

        ip = _get_client_ip(mock_request)
        assert ip == "unknown"

    def test_record_request_appends(self):
        """_record_request adds entry to log."""
        from riks_context_engine.api.server import _ip_request_log, _record_request

        ip = "record-test-ip"
        _record_request(ip)
        _record_request(ip)

        entries = _ip_request_log[ip]
        assert len(entries) >= 2

    def test_rate_limit_headers_configurable(self):
        """Rate limit values are configurable via env vars."""
        with patch.dict("os.environ", {"RATE_LIMIT_REQUESTS": "50", "RATE_LIMIT_WINDOW": "30"}):
            # Re-import to pick up new env values
            import importlib

            import riks_context_engine.api.server as server_module

            importlib.reload(server_module)

            assert server_module._RATE_LIMIT_REQUESTS == 50
            assert server_module._RATE_LIMIT_WINDOW == 30
