"""Pytest fixtures for API integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riks_context_engine.api.server import app


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c
