"""Pytest fixtures for API integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api.server import app, get_engine
from riks_context_engine.api import server as server_module


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset the module-level engine before each test for a clean in-memory state."""
    server_module._engine = None
    yield
    server_module._engine = None


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def engine():
    """Return a fresh engine instance."""
    server_module._engine = None
    return get_engine()
