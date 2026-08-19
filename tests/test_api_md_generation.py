"""Tests for the API.md auto-generation (#141, issue #123 turn 3).

Verifies that ``docs/API.md`` contains a section generated from the OpenAPI
spec (``GET /openapi.json`` / ``app.openapi()``) and that the generated
section lists every expected endpoint. Also verifies that regenerating the
section is idempotent (running the generator does not change the section).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from riks_context_engine.api.server import app

REPO_ROOT = Path(__file__).resolve().parents[1]
API_MD = REPO_ROOT / "docs" / "API.md"
GENERATOR = REPO_ROOT / "scripts" / "generate_api_md.py"

BEGIN = "<!-- AUTO:HTTP-API:BEGIN"
END = "<!-- AUTO:HTTP-API:END -->"

EXPECTED_ENDPOINTS = [
    ("GET", "/health"),
    ("GET", "/models"),
    ("POST", "/api/chat"),
    ("GET", "/api/v1/context/messages"),
    ("POST", "/api/v1/context/messages"),
    ("GET", "/api/v1/context/summary"),
    ("GET", "/api/v1/memory/export"),
    ("POST", "/api/v1/memory/import"),
]


def _generated_section() -> str:
    """Extract the generated section from docs/API.md (between sentinels)."""
    text = API_MD.read_text(encoding="utf-8")
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    return text[start:end]


def _spec() -> dict:
    with TestClient(app) as client:
        res = client.get("/openapi.json")
        assert res.status_code == 200
        data = res.json()
    assert isinstance(data, dict)
    return data


class TestApiMdGenerated:
    def test_sentinels_present(self):
        section = _generated_section()
        assert BEGIN in section
        assert END in section

    def test_generator_metadata_present(self):
        section = _generated_section()
        assert "Oluşturuldu" in section, "generator metadata line missing"
        assert "scripts/generate_api_md.py" in section
        assert "otomatik üretilmiştir" in section

    def test_expected_endpoints_in_generated_section(self):
        """Kritik 4: the generated section lists every expected endpoint."""
        section = _generated_section()
        spec = _spec()
        # Every endpoint in the spec must appear in the generated section.
        for method, path in EXPECTED_ENDPOINTS:
            assert f"`{method.upper()} {path}`" in section, (
                f"{method.upper()} {path} missing from generated API.md section"
            )
        # Cross-check against the spec: every spec path/method is covered.
        for path, ops in spec.get("paths", {}).items():
            for method in ops:
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue
                if method.upper() == "GET" and path == "/":
                    continue  # root alias excluded from the spec (include_in_schema=False)
                assert f"`{method.upper()} {path}`" in section, (
                    f"{method.upper()} {path} in spec but missing from API.md"
                )

    def test_generated_section_has_schemas_and_examples(self):
        """The generated section must include request/response schemas and
        example payloads (issue criterion: şema + örnek payload)."""
        section = _generated_section()
        assert "Request body" in section
        assert "Response (200)" in section
        assert "Example" in section
        # The examples come from the spec (_apply_openapi_examples +
        # Field(examples=...)); assert at least one known example value.
        assert "gemma4-31b-it" in section

    def test_regeneration_is_idempotent(self, tmp_path: Path):
        """Running the generator --write must not change the generated
        section (except the timestamp line)."""
        import re

        # Copy docs/API.md to a temp location and run the generator with the
        # repo's docs path (the generator writes to the repo docs/API.md; we
        # verify the section is stable by comparing before/after, ignoring
        # the timestamp line).
        original = _generated_section()

        # Strip the timestamp line (it changes on every run).
        def strip_ts(s: str) -> str:
            return re.sub(
                r"<!-- Oluşturuldu: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC —",
                "<!-- Oluşturuldu: TIMESTAMP —",
                s,
            )

        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--write"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        regenerated = _generated_section()
        assert strip_ts(original) == strip_ts(regenerated), (
            "regenerating the section changed its content (non-idempotent)"
        )
