"""Tests for KnowledgeGraph embedder fallback logging (issue #52)."""

import logging
from unittest.mock import patch

import pytest

from riks_context_engine.graph.knowledge_graph import EntityType, KnowledgeGraph


class FailingEmbedder:
    """Embedder that always raises to test fallback path."""

    def embed(self, text: str):
        raise RuntimeError("Embedder unavailable")


class TimeoutEmbedder:
    """Embedder that times out."""

    def embed(self, text: str):
        raise TimeoutError("Connection timed out")


class TestKnowledgeGraphFallbackLogging:
    def test_embedder_failure_logs_warning(self):
        """When embedder fails, a WARNING should be logged before keyword fallback."""
        kg = KnowledgeGraph()
        kg.add_entity("Vahit", EntityType.PERSON, {"role": "DevSecOps Lead"})

        with patch("riks_context_engine.graph.knowledge_graph.logger") as mock_logger:
            results = kg.semantic_search("Vahit", top_k=5, embedder=FailingEmbedder())

            # Should still return results via keyword fallback
            assert len(results) >= 1
            assert results[0][0].name == "Vahit"

            # WARNING must be emitted
            mock_logger.warning.assert_called_once()
            all_call_args = mock_logger.warning.call_args
            call_args = all_call_args[0]
            # call_args = (format_str, exc_type_name, exc_value)
            assert "falling back to keyword search" in call_args[0], \
                f"Format string mismatch: {call_args[0]!r}"
            assert len(call_args) == 3, f"Expected 3 args, got {len(call_args)}: {call_args!r}"
            assert "RuntimeError" in str(call_args[1]), f"Expected RuntimeError, got {call_args[1]!r}"

    def test_embedder_timeout_logs_warning(self):
        """When embedder times out, a WARNING should be logged before keyword fallback."""
        kg = KnowledgeGraph()
        kg.add_entity("Rik", EntityType.CONCEPT, {"domain": "AI"})

        with patch("riks_context_engine.graph.knowledge_graph.logger") as mock_logger:
            results = kg.semantic_search("Rik", top_k=5, embedder=TimeoutEmbedder())

            assert len(results) >= 1
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0]
            assert "falling back to keyword search" in call_args[0]
            # call_args = (format_str, exc_type_name, exc_value)
            assert "TimeoutError" in str(call_args[1]), f"Expected TimeoutError, got {call_args[1]!r}"
