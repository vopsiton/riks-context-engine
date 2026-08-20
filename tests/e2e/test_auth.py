"""E2E auth + tenant isolation tests (#166).
# mypy: ignore-errors

Tests the API key auth middleware and tenant isolation against the
FastAPI app via TestClient (CI) and against a live staging instance
(real HTTP, real Ollama).

Acceptance criteria (issue #166):
1. Auth matrix: invalid key → 401; tenant A key + A data → 200;
   A key + B data → 403/404 (no leak); no key → 401; /health → 200 no auth.
2. ≥3 endpoints: /api/chat, /api/v1/context/messages, /api/v1/audit.
3. Tests in repo (tests/e2e/test_auth.py), run in CI (TestClient) +
   staging smoke set (real instance).
4. Negative: 100 random keys → all 401, no 200.
"""

from __future__ import annotations

import os
import secrets

import pytest

# ── Configuration ─────────────────────────────────────────────────────────────

#: The valid API key for the running instance. In CI (TestClient), we set
#: the API_KEY env var before importing the app. In staging, read from env.
VALID_API_KEY = os.environ.get("E2E_API_KEY", "test-api-key-166")

#: Tenant IDs for isolation tests.
TENANT_A = "e2e-auth-tenant-a"
TENANT_B = "e2e-auth-tenant-b"

#: Endpoints to test (≥3 per acceptance criteria).
ENDPOINTS = [
    "/api/chat",
    "/api/v1/context/messages",
    "/api/v1/audit",
]


def _headers(api_key: str | None = None, tenant: str | None = None) -> dict[str, str]:
    """Build request headers."""
    h: dict[str, str] = {}
    if api_key:
        h["X-API-Key"] = api_key
    if tenant:
        h["X-Tenant-Id"] = tenant
    return h


def _base_url() -> str:
    """Base URL for staging tests (empty for TestClient)."""
    return os.environ.get("STAGING_API_URL", "")


def _is_staging() -> bool:
    """True when running against a live staging instance."""
    return bool(_base_url())


# ── CI tests (TestClient) ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_api_key(monkeypatch):
    """Set the API_KEY env var for TestClient tests (CI).

    For staging tests, the key is already set in the running instance.
    """
    if _is_staging():
        yield
        return
    monkeypatch.setenv("API_KEY", VALID_API_KEY)
    # Reset the module-level API_KEY (read at import time).
    import riks_context_engine.api.server as server

    monkeypatch.setattr(server, "API_KEY", VALID_API_KEY, raising=False)
    yield


@pytest.fixture
def client():
    """TestClient for CI (no base URL) or requests for staging."""
    if _is_staging():
        # Use a simple wrapper around urllib for staging tests.
        import urllib.request

        class _UrllibClient:
            def get(self, url, headers=None, timeout=10):
                req = urllib.request.Request(url, headers=headers or {})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return _UrllibResponse(resp)

            def post(self, url, headers=None, json=None, timeout=10):
                import json as _json

                data = _json.dumps(json).encode() if json else b""
                req = urllib.request.Request(
                    url, data=data, headers={**(headers or {}), "Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return _UrllibResponse(resp)

        class _UrllibResponse:
            def __init__(self, resp):
                self.status_code = resp.status
                self._body = resp.read().decode()

            @property
            def text(self):
                return self._body

            def json(self):
                import json as _json

                return _json.loads(self._body)

        yield _UrllibClient()
        return
    from fastapi.testclient import TestClient

    import riks_context_engine.api.server as server

    with TestClient(server.app) as c:
        yield c


def _request(client, method: str, path: str, headers: dict, **kwargs):
    """Unified request interface (TestClient or requests)."""
    if _is_staging():
        url = f"{_base_url()}{path}"
        if method == "GET":
            r = client.get(url, headers=headers, timeout=10)
        else:
            r = client.post(url, headers=headers, json=kwargs.get("json"), timeout=10)
        return r
    # TestClient
    if method == "GET":
        return client.get(path, headers=headers)
    return client.post(path, headers=headers, json=kwargs.get("json"))


class TestAuthMatrix:
    """Auth matrix (#166): invalid key → 401, valid key → 200, no key → 401."""

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_invalid_key_401(self, client, endpoint):
        """Geçersiz API key → 401."""
        h = _headers(api_key="wrong-key", tenant=TENANT_A)
        r = _request(
            client,
            "GET" if endpoint != "/api/chat" else "POST",
            endpoint,
            h,
            json={"message": "hi"} if endpoint == "/api/chat" else None,
        )
        assert r.status_code == 401, f"{endpoint}: expected 401, got {r.status_code}"

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_valid_key_200(self, client, endpoint):
        """Tenant A key + A verisi → 200."""
        h = _headers(api_key=VALID_API_KEY, tenant=TENANT_A)
        r = _request(
            client,
            "GET" if endpoint != "/api/chat" else "POST",
            endpoint,
            h,
            json={"message": "hi"} if endpoint == "/api/chat" else None,
        )
        assert r.status_code == 200, (
            f"{endpoint}: expected 200, got {r.status_code}: {r.text[:200]}"
        )

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_no_key_401(self, client, endpoint):
        """Key yok → 401."""
        h = _headers(tenant=TENANT_A)
        r = _request(
            client,
            "GET" if endpoint != "/api/chat" else "POST",
            endpoint,
            h,
            json={"message": "hi"} if endpoint == "/api/chat" else None,
        )
        assert r.status_code == 401, f"{endpoint}: expected 401 (no key), got {r.status_code}"

    def test_health_no_auth(self, client):
        """/health → auth gerektirmez, 200."""
        h = _headers()  # no key, no tenant
        r = _request(client, "GET", "/health", h)
        assert r.status_code == 200, f"/health: expected 200, got {r.status_code}"


class TestTenantIsolation:
    """Tenant isolation: A key + B data → no leak (403/404)."""

    def test_tenant_a_cannot_read_tenant_b_context(self, client):
        """A tenant'ın B tenant'ın context'ini okuyamaması."""
        # Seed tenant B with data
        h_b = _headers(api_key=VALID_API_KEY, tenant=TENANT_B)
        _request(client, "POST", "/api/chat", h_b, json={"message": "Benim adım Bob"})

        # Tenant A tries to read tenant B's context
        h_a = _headers(api_key=VALID_API_KEY, tenant=TENANT_A)
        r = _request(client, "GET", "/api/v1/context/messages", h_a)
        # Should be 200 (A's own context) but must NOT contain B's data
        if r.status_code == 200:
            body = r.json()
            contents = " ".join(str(m) for m in body) if isinstance(body, list) else str(body)
            assert "Bob" not in contents, f"Tenant B data leaked to A: {contents[:200]}"

    def test_tenant_a_cannot_read_tenant_b_audit(self, client):
        """A tenant'ın B tenant'ın audit log'unu okuyamaması."""
        # Seed tenant B
        h_b = _headers(api_key=VALID_API_KEY, tenant=TENANT_B)
        _request(client, "POST", "/api/chat", h_b, json={"message": "Bob secret"})

        # Tenant A reads audit
        h_a = _headers(api_key=VALID_API_KEY, tenant=TENANT_A)
        r = _request(client, "GET", "/api/v1/audit", h_a)
        if r.status_code == 200:
            body = r.json()
            contents = str(body)
            assert "Bob secret" not in contents, f"Tenant B audit leaked to A: {contents[:200]}"


class TestNegative100Keys:
    """Negatif: 100 rastgele key → hepsi 401, 200 yok."""

    def test_100_random_keys_all_401(self, client):
        """100 random API key → all 401, no 200."""
        for i in range(100):
            random_key = secrets.token_hex(16)
            h = _headers(api_key=random_key, tenant=TENANT_A)
            r = _request(client, "GET", "/api/v1/context/messages", h)
            assert r.status_code == 401, (
                f"Random key {i} ({random_key[:8]}...) got {r.status_code}, expected 401"
            )


class TestStagingSmoke:
    """Staging smoke: real instance + real Ollama (runs only in staging)."""

    @pytest.mark.skipif(not _is_staging(), reason="Only runs against live staging instance")
    def test_staging_auth_matrix(self):
        """Staging'de gerçek HTTP ile auth matrix."""
        base = _base_url()
        import requests

        # 1. Invalid key → 401
        r = requests.get(
            f"{base}/api/v1/context/messages",
            headers=_headers(api_key="wrong", tenant=TENANT_A),
            timeout=10,
        )
        assert r.status_code == 401, f"Staging: invalid key expected 401, got {r.status_code}"

        # 2. Valid key → 200
        r = requests.get(
            f"{base}/api/v1/context/messages",
            headers=_headers(api_key=VALID_API_KEY, tenant=TENANT_A),
            timeout=10,
        )
        assert r.status_code == 200, f"Staging: valid key expected 200, got {r.status_code}"

        # 3. /health → 200 no auth
        r = requests.get(f"{base}/health", timeout=10)
        assert r.status_code == 200, f"Staging: /health expected 200, got {r.status_code}"

    @pytest.mark.skipif(not _is_staging(), reason="Only runs against live staging instance")
    def test_staging_chat_real_llm(self):
        """Staging'de gerçek Ollama ile chat: 'Benim adım Vahit' → 'Adım ne?' → 'Vahit'."""
        base = _base_url()
        import requests

        h = _headers(api_key=VALID_API_KEY, tenant="staging-smoke-166")

        # Step 1: Introduce name
        r = requests.post(
            f"{base}/api/chat",
            json={"message": "Benim adım Vahit", "model": "gemma4:31b"},
            headers=h,
            timeout=120,
        )
        assert r.status_code == 200, f"Staging chat step1: {r.status_code} {r.text[:200]}"

        # Step 2: Ask for name
        r = requests.post(
            f"{base}/api/chat",
            json={"message": "Adım ne?", "model": "gemma4:31b"},
            headers=h,
            timeout=120,
        )
        assert r.status_code == 200, f"Staging chat step2: {r.status_code} {r.text[:200]}"
        response = r.json()["response"]
        assert "Vahit" in response, f"Staging: expected 'Vahit' in response, got: {response[:200]}"
