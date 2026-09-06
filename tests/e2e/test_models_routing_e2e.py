"""E2E tests for GET /models + model routing [P2] (#172).

Acceptance criteria mapping:

- AC1 (list models): :class:`TestModelsList`
- AC2 (routing): :class:`TestModelRouting`
- AC3 (verification): :class:`TestModelAttribution`
- AC4 (default model): :class:`TestDefaultModel`
- AC5 (stability): :class:`TestModelsStability`

MEASURED BEHAVIOR (not assumed):

- ``GET /models`` returns ``{"models": [...]}`` where each entry is a
  plain string (model id). The response schema is ``ModelsResponse``
  (a single field ``models: list[str]``), NOT OpenAI-compatible
  (which would be ``{"data": [{"id": ..., "object": ...}]}``).
- The model list is a module-level constant ``_MODELS`` (server.py:70),
  not fetched from a live LLM backend. It is deterministic and stable
  across requests.
- ``POST /api/chat`` with ``model=X`` where ``X in _MODELS`` → 200.
  The response includes ``{"response": ..., "model": X}`` — the model
  field echoes back the requested model (attribution is correct).
- ``POST /api/chat`` with ``model=BOZUK`` (not in ``_MODELS``) → 400
  with ``detail="Unknown model: BOZUK"``. This is a validation check
  against the static list, not a live LLM routing check.
- ``POST /api/chat`` without a ``model`` field → defaults to
  ``"gemma4:31b"`` (hardcoded fallback in server.py:945).
- The LLM call itself: if ``LLM_PROVIDER_URL`` is set, a real provider
  call is made. Otherwise, a deterministic stub (``_stub_llm``) is
  used. In CI (no provider), the stub always returns a response
  prefixed with ``[model]`` — the model attribution is verifiable
  from the response prefix.
- Auth: ``/models`` and ``/api/chat`` are in ``_API_KEY_PROTECTED_PATHS``.
  Missing ``X-API-Key`` or ``X-Tenant-Id`` → 401.

SCOPE: test-only. No product code changes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import _MODELS, app

WS_KEY = "***"
TENANT = "t172"


def _setup_headers() -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-API-Key": WS_KEY}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    """Ensure API_KEY is set and no LLM provider is configured (stub mode).

    The middleware reads ``server_module.API_KEY`` (a module-level
    constant captured at import time), NOT ``os.environ`` directly.
    So we patch the module attribute, not the env var.
    """
    original_key = server_module.API_KEY
    server_module.API_KEY = WS_KEY
    monkeypatch.delenv("LLM_PROVIDER_URL", raising=False)
    yield
    server_module.API_KEY = original_key


# ─── AC1: GET /models — list models ──────────────────────────────────────────


class TestModelsList:
    """GET /models returns the available model list."""

    def test_returns_200(self):
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.get("/models")
            assert resp.status_code == 200

    def test_response_has_models_field(self):
        """Response body is ``{"models": [...]}`` — the ``ModelsResponse``
        schema (NOT OpenAI-compatible ``{"data": [...]}``)."""
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.get("/models")
            body = resp.json()
            assert "models" in body, f"expected 'models' field, got keys: {list(body.keys())}"
            assert isinstance(body["models"], list)

    def test_at_least_one_model(self):
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.get("/models")
            models = resp.json()["models"]
            assert len(models) >= 1, "expected at least 1 model"

    def test_all_entries_are_nonempty_strings(self):
        """Each model entry must be a non-empty string (model id)."""
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.get("/models")
            models = resp.json()["models"]
            for m in models:
                assert isinstance(m, str), f"model entry not a string: {type(m)}"
                assert len(m) > 0, "model entry is empty"

    def test_known_models_present(self):
        """The static _MODELS list is exposed verbatim (deterministic,
        no live backend). At minimum the default model must be present."""
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.get("/models")
            models = resp.json()["models"]
            assert "gemma4:31b" in models, "default model not in list"
            # The full list should match the module constant
            assert models == _MODELS, f"model list mismatch: {models} != {_MODELS}"

    def test_401_without_api_key(self):
        """/models is protected: missing X-API-Key → 401."""
        headers = {"X-Tenant-Id": TENANT}
        with TestClient(app, headers=headers) as client:
            resp = client.get("/models")
            assert resp.status_code == 401

    def test_401_without_tenant(self):
        """/models is protected: missing X-Tenant-Id → 401."""
        headers = {"X-API-Key": WS_KEY}
        with TestClient(app, headers=headers) as client:
            resp = client.get("/models")
            assert resp.status_code == 401


# ─── AC2: model routing — /api/chat with model param ────────────────────────


class TestModelRouting:
    """/api/chat with model=X routes to the specified model (or rejects)."""

    def test_valid_model_returns_200(self):
        """POST /api/chat with a model from the /models list → 200."""
        model = _MODELS[0]
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.post("/api/chat", json={"message": "hi", "model": model})
            assert resp.status_code == 200

    def test_response_echoes_requested_model(self):
        """The response body's ``model`` field echoes back the requested
        model — attribution is correct."""
        model = _MODELS[1] if len(_MODELS) > 1 else _MODELS[0]
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.post("/api/chat", json={"message": "hi", "model": model})
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("model") == model, (
                f"expected model={model!r}, got {body.get('model')!r}"
            )

    def test_unknown_model_returns_400(self):
        """POST /api/chat with model=BOZUK (not in _MODELS) → 400 with
        a clear error message (not 500)."""
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.post("/api/chat", json={"message": "hi", "model": "BOZUK"})
            assert resp.status_code == 400, f"expected 400, got {resp.status_code}"
            body = resp.json()
            detail = body.get("detail", "")
            assert "BOZUK" in detail, f"expected model name in error, got: {detail}"

    def test_all_listed_models_accepted(self):
        """Every model in /models is accepted by /api/chat (routing
        covers the full list)."""
        with TestClient(app, headers=_setup_headers()) as client:
            for model in _MODELS:
                resp = client.post("/api/chat", json={"message": "hi", "model": model})
                assert resp.status_code == 200, (
                    f"model={model!r} rejected: {resp.status_code} {resp.text}"
                )

    def test_401_without_api_key(self):
        """/api/chat is protected: missing X-API-Key → 401."""
        headers = {"X-Tenant-Id": TENANT}
        with TestClient(app, headers=headers) as client:
            resp = client.post("/api/chat", json={"message": "hi"})
            assert resp.status_code == 401

    def test_401_without_tenant(self):
        """/api/chat is protected: missing X-Tenant-Id → 401."""
        headers = {"X-API-Key": WS_KEY}
        with TestClient(app, headers=headers) as client:
            resp = client.post("/api/chat", json={"message": "hi"})
            assert resp.status_code == 401


# ─── AC3: model attribution — response reflects the model used ─────────────


class TestModelAttribution:
    """The LLM response is attributed to the requested model.

    In stub mode (no LLM_PROVIDER_URL), the deterministic stub prefixes
    its response with ``[model]``. This is the strongest attribution
    signal available without a live LLM: the response text itself
    carries the model identifier.

    GAP NOTE: In production (LLM_PROVIDER_URL set), the model attribution
    is verified via the provider's response, not a local prefix. The
    routing decision (which model string is sent to the provider) is
    the same code path tested here. A future enhancement could add an
    OpenTelemetry span attribute for the routed model to make this
    verifiable without relying on response text.
    """

    def test_stub_response_prefixed_with_model(self):
        """In stub mode, the response starts with ``[model]`` — the
        model attribution is embedded in the response itself."""
        model = _MODELS[0]
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.post("/api/chat", json={"message": "hello", "model": model})
            assert resp.status_code == 200
            body = resp.json()
            response_text = body.get("response", "")
            assert response_text.startswith(f"[{model}]"), (
                f"expected response prefixed with [{model}], got: {response_text[:50]!r}"
            )

    def test_different_models_produce_different_attribution(self):
        """Two different models → two different attribution prefixes.
        Same prompt, different model → different response prefix.
        This proves the routing actually changes the model used."""
        model_a = _MODELS[0]
        model_b = _MODELS[1] if len(_MODELS) > 1 else _MODELS[0]
        if model_a == model_b:
            pytest.skip("need at least 2 distinct models")
        prompt = "hello"
        with TestClient(app, headers=_setup_headers()) as client:
            resp_a = client.post("/api/chat", json={"message": prompt, "model": model_a})
            resp_b = client.post("/api/chat", json={"message": prompt, "model": model_b})
            assert resp_a.status_code == 200
            assert resp_b.status_code == 200
            body_a = resp_a.json()
            body_b = resp_b.json()
            assert body_a["model"] == model_a
            assert body_b["model"] == model_b
            # The response text carries the model prefix
            assert body_a["response"].startswith(f"[{model_a}]")
            assert body_b["response"].startswith(f"[{model_b}]")
            # The prefixes differ (different models)
            assert body_a["response"] != body_b["response"], (
                "responses identical despite different models"
            )

    def test_model_field_matches_response_prefix(self):
        """The ``model`` field in the response body must match the model
        prefix in the response text (consistent attribution)."""
        for model in _MODELS:
            with TestClient(app, headers=_setup_headers()) as client:
                resp = client.post("/api/chat", json={"message": "test", "model": model})
                assert resp.status_code == 200
                body = resp.json()
                assert body["model"] == model
                assert body["response"].startswith(f"[{model}]"), (
                    f"model field={model!r} but response prefix mismatch: {body['response'][:50]!r}"
                )


# ─── AC4: default model ─────────────────────────────────────────────────────


class TestDefaultModel:
    """When no model is specified, the default model is used."""

    def test_no_model_defaults_to_gemma4_31b(self):
        """POST /api/chat without a ``model`` field → defaults to
        ``"gemma4:31b"`` (hardcoded fallback in server.py:945)."""
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.post("/api/chat", json={"message": "hi"})
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("model") == "gemma4:31b", (
                f"expected default model 'gemma4:31b', got {body.get('model')!r}"
            )

    def test_null_model_defaults_to_gemma4_31b(self):
        """Explicit null model → same default."""
        with TestClient(app, headers=_setup_headers()) as client:
            resp = client.post("/api/chat", json={"message": "hi", "model": None})
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("model") == "gemma4:31b"

    def test_default_model_is_in_listed_models(self):
        """The default model must also be in the /models list."""
        with TestClient(app, headers=_setup_headers()) as client:
            models_resp = client.get("/models")
            models = models_resp.json()["models"]
            chat_resp = client.post("/api/chat", json={"message": "hi"})
            default_model = chat_resp.json().get("model")
            assert default_model in models, (
                f"default model {default_model!r} not in /models list: {models}"
            )


# ─── AC5: stability — model list is deterministic ───────────────────────────


class TestModelsStability:
    """The model list must be stable across consecutive requests."""

    def test_model_list_stable_across_3_requests(self):
        """3 consecutive GET /models → identical lists (deterministic)."""
        with TestClient(app, headers=_setup_headers()) as client:
            lists = []
            for _ in range(3):
                resp = client.get("/models")
                assert resp.status_code == 200
                lists.append(resp.json()["models"])
            assert lists[0] == lists[1] == lists[2], (
                f"model list unstable:\n  req 1: {lists[0]}\n  req 2: {lists[1]}\n  req 3: {lists[2]}"
            )

    def test_model_order_stable(self):
        """Model list order is stable (not shuffled between requests)."""
        with TestClient(app, headers=_setup_headers()) as client:
            r1 = client.get("/models").json()["models"]
            r2 = client.get("/models").json()["models"]
            assert r1 == r2, f"model order changed: {r1} vs {r2}"
