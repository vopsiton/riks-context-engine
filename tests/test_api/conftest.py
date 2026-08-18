"""Pytest fixtures for API integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api import server as server_module
from riks_context_engine.api.server import app


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset the module-level memory instances before each test."""
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None
    yield
    server_module._episodic_memory = None
    server_module._semantic_memory = None
    server_module._procedural_memory = None


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app.

    Sends a valid X-Tenant-Id header so the tenant-isolation middleware
    (which 401s on every protected path without a well-formed tenant)
    lets API calls through. Tests asserting tenant validation (401)
    should pass explicit headers to override this default.
    """
    with TestClient(app, headers={"X-Tenant-Id": "test-tenant"}) as c:
        yield c
