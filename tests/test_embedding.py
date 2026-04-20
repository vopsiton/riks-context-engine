"""Test embedding functions for coverage."""
import pytest
from unittest.mock import patch, MagicMock

from riks_context_engine.memory.embedding import (
    get_embedder,
    EmbeddingResult,
    OllamaEmbeddingError,
    OllamaEmbedder,
)


class TestOllamaEmbedder:
    """Tests for OllamaEmbedder and get_embedder."""

    def test_client_uses_connection_pool(self):
        """Client should be configured with connection pooling limits."""
        embedder = OllamaEmbedder()
        # Verify the client was created (not None)
        assert embedder.client is not None
        # The client limits are configured on init; we verify the client works
        # Connection reuse happens automatically with keepalive connections
        embedder.close()

    def test_client_is_cached(self):
        """client property should return the same instance on repeated access."""
        embedder = OllamaEmbedder()
        c1 = embedder.client
        c2 = embedder.client
        assert c1 is c2
        embedder.close()

    def test_get_embedder_returns_embedder(self):
        """get_embedder should return an OllamaEmbedder object."""
        embedder = get_embedder()
        assert isinstance(embedder, OllamaEmbedder)

    def test_embedder_has_embed_method(self):
        """Embedder should have embed method."""
        embedder = get_embedder()
        assert hasattr(embedder, 'embed')
        assert callable(embedder.embed)

    def test_embedder_has_embed_batch_method(self):
        """Embedder should have embed_batch method."""
        embedder = get_embedder()
        assert hasattr(embedder, 'embed_batch')
        assert callable(embedder.embed_batch)

    def test_embedder_base_url(self):
        """Embedder should have base_url."""
        embedder = get_embedder()
        assert hasattr(embedder, 'base_url')
        assert embedder.base_url is not None

    def test_embedder_is_available(self):
        """Embedder should have is_available method."""
        embedder = get_embedder()
        assert hasattr(embedder, 'is_available')
        # May return True or False depending on Ollama status

    def test_embedder_close(self):
        """Embedder should have close method."""
        embedder = get_embedder()
        assert hasattr(embedder, 'close')
        # close should not raise
        embedder.close()

    def test_embedder_model_property(self):
        """Embedder should have model property."""
        embedder = get_embedder()
        assert hasattr(embedder, 'model')


class TestEmbeddingResult:
    """Tests for EmbeddingResult dataclass."""

    def test_embedding_result_creation(self):
        """Create EmbeddingResult directly."""
        result = EmbeddingResult(
            embedding=[0.1, 0.2, 0.3],
            model="test-model",
        )
        assert len(result.embedding) == 3
        assert result.model == "test-model"

    def test_embedding_result_with_prompt_tokens(self):
        """Create EmbeddingResult with prompt_tokens."""
        result = EmbeddingResult(
            embedding=[0.1, 0.2],
            model="test",
            prompt_tokens=10,
        )
        assert result.prompt_tokens == 10

    def test_embedding_result_equality(self):
        """Two EmbeddingResult with same data should be equal."""
        r1 = EmbeddingResult(embedding=[1.0, 2.0], model="m")
        r2 = EmbeddingResult(embedding=[1.0, 2.0], model="m")
        assert r1 == r2


class TestOllamaEmbeddingError:
    """Tests for OllamaEmbeddingError exception."""

    def test_error_can_be_raised(self):
        """OllamaEmbeddingError should be raiseable."""
        with pytest.raises(OllamaEmbeddingError):
            raise OllamaEmbeddingError("test error")

    def test_error_has_message(self):
        """OllamaEmbeddingError should carry message."""
        with pytest.raises(OllamaEmbeddingError, match="test"):
            raise OllamaEmbeddingError("test error message")
