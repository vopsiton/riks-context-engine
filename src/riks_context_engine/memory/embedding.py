"""Ollama embedding service for vector representations."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    embedding: list[float]
    model: str
    prompt_tokens: int | None = None


class OllamaEmbeddingError(Exception):
    """Raised when embedding generation fails."""


class OllamaEmbedder:
    """Generates vector embeddings via Ollama API.

    Uses the nomic-embed-text model by default for
    high-quality semantic representations.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str = "nomic-embed-text",
        timeout: float = 30.0,
    ):
        self.base_url = base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.model = model
        self.timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text string."""
        try:
            response = self.client.post(
                "/api/embed",
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
            data = response.json()

            # Ollama /api/embed returns {"embeddings": [[...]], "model": "...", "prompt_eval_count": N}
            embeddings: list[list[float]] = data.get("embeddings", [])
            if not embeddings:
                raise OllamaEmbeddingError("No embeddings returned from Ollama")

            return EmbeddingResult(
                embedding=embeddings[0],
                model=self.model,
                prompt_tokens=data.get("prompt_eval_count"),
            )
        except httpx.ConnectError as exc:
            msg = f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?"
            raise OllamaEmbeddingError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = f"Ollama API error: {exc.response.status_code} {exc.response.text}"
            raise OllamaEmbeddingError(msg) from exc
        except (KeyError, ValueError) as exc:
            msg = f"Unexpected Ollama response format: {exc}"
            raise OllamaEmbeddingError(msg) from exc

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts in one API call."""
        try:
            response = self.client.post(
                "/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()

            embeddings: list[list[float]] = data.get("embeddings", [])
            if len(embeddings) != len(texts):
                msg = f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                raise OllamaEmbeddingError(msg)

            prompt_tokens = data.get("prompt_eval_count")
            return [
                EmbeddingResult(
                    embedding=emb,
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                )
                for emb in embeddings
            ]
        except httpx.ConnectError as exc:
            msg = f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?"
            raise OllamaEmbeddingError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = f"Ollama API error: {exc.response.status_code} {exc.response.text}"
            raise OllamaEmbeddingError(msg) from exc
        except (KeyError, ValueError) as exc:
            msg = f"Unexpected Ollama response format: {exc}"
            raise OllamaEmbeddingError(msg) from exc

    def is_available(self) -> bool:
        """Check whether the Ollama service is reachable."""
        try:
            response = self.client.get("/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None


# Module-level singleton for convenience
_default_embedder: OllamaEmbedder | None = None


def get_embedder() -> OllamaEmbedder:
    """Return the default module-level embedder instance."""
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = OllamaEmbedder()
    return _default_embedder


def set_embedder(embedder: OllamaEmbedder) -> None:
    """Replace the default module-level embedder."""
    global _default_embedder
    _default_embedder = embedder
