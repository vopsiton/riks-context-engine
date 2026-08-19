"""Tests for the semantic_write MCP tool (#108)."""

from __future__ import annotations

import os

import pytest

from riks_context_engine.mcp.handlers import TenantIsolationError, ToolHandler
from riks_context_engine.mcp.schemas import TOOL_SCHEMAS


class TestSemanticWriteSchema:
    """Verify the semantic_write tool schema is registered correctly."""

    def test_schema_exists(self):
        assert "semantic_write" in TOOL_SCHEMAS

    def test_required_fields(self):
        schema = TOOL_SCHEMAS["semantic_write"]["inputSchema"]
        assert set(schema["required"]) == {"tenant_id", "subject", "predicate"}

    def test_additional_properties_forbidden(self):
        schema = TOOL_SCHEMAS["semantic_write"]["inputSchema"]
        assert schema.get("additionalProperties") is False


class TestSemanticWriteSuccess:
    """Write + query round-trip within the same tenant."""

    def test_write_and_query_same_tenant(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        result = handler.semantic_write(
            {
                "tenant_id": "agentA",
                "subject": "auth_service",
                "predicate": "uses",
                "object": "JWT RS256",
                "confidence": 0.95,
            }
        )
        assert result["status"] == "written"
        assert result["subject"] == "auth_service"
        assert result["predicate"] == "uses"
        assert result["object"] == "JWT RS256"
        assert result["confidence"] == 0.95
        assert "id" in result

        semantic = handler._get_semantic("agentA")
        entries = semantic.query(subject="auth_service")
        assert len(entries) == 1
        assert entries[0].predicate == "uses"


class TestSemanticWriteIsolation:
    """Cross-tenant isolation: agentA's data is invisible to agentB."""

    def test_cross_tenant_invisible(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        handler.semantic_write(
            {
                "tenant_id": "agentA",
                "subject": "secret_key",
                "predicate": "is",
                "object": "abc123",
            }
        )

        path_b = os.path.join(str(tmp_path), "tenants", "agentB")
        assert not os.path.exists(path_b), "agentB dir should not exist before query"

        semantic_b = handler._get_semantic("agentB")
        entries = semantic_b.query(subject="secret_key")
        assert len(entries) == 0


class TestSemanticWriteTenantValidation:
    """Tenant id validation edge cases."""

    def test_missing_tenant_id(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        with pytest.raises(TenantIsolationError):
            handler.semantic_write({"subject": "x", "predicate": "y"})

    def test_empty_tenant_id(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        with pytest.raises(TenantIsolationError):
            handler.semantic_write({"tenant_id": "", "subject": "x", "predicate": "y"})

    def test_path_traversal_tenant_id(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        with pytest.raises(TenantIsolationError):
            handler.semantic_write({"tenant_id": "../etc", "subject": "x", "predicate": "y"})


class TestSemanticWriteValidation:
    """Pydantic validation with extra='forbid'."""

    def test_confidence_out_of_range(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        with pytest.raises(TenantIsolationError, match="confidence"):
            handler.semantic_write(
                {
                    "tenant_id": "agentA",
                    "subject": "x",
                    "predicate": "y",
                    "confidence": 1.5,
                }
            )

    def test_empty_subject(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        with pytest.raises(TenantIsolationError, match="subject"):
            handler.semantic_write(
                {
                    "tenant_id": "agentA",
                    "subject": "",
                    "predicate": "y",
                }
            )

    def test_extra_field_rejected(self, tmp_path):
        handler = ToolHandler(data_dir=str(tmp_path))
        with pytest.raises(TenantIsolationError):
            handler.semantic_write(
                {
                    "tenant_id": "agentA",
                    "subject": "x",
                    "predicate": "y",
                    "evil_field": "drop table;",
                }
            )
