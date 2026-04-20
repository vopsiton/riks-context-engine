"""
UI E2E Test — Rik Context Engine Web UI
"""

import requests

API_BASE = "http://127.0.0.1:9000"


class TestUIBasicConnectivity:
    def test_ui_loads(self):
        r = requests.get(f"{API_BASE}/", timeout=5)
        assert r.status_code == 200
        assert "Rik Context Engine" in r.text

    def test_health(self):
        r = requests.get(f"{API_BASE}/health", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_models(self):
        r = requests.get(f"{API_BASE}/models", timeout=5)
        assert r.status_code == 200
        assert len(r.json().get("models", [])) > 0
