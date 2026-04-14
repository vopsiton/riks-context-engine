"""3-tier memory system: Episodic, Semantic, Procedural."""

from .base import MemoryEntry, MemoryType
from .embedding import OllamaEmbedder, OllamaEmbeddingError, get_embedder, set_embedder
from .episodic import EpisodicEntry, EpisodicMemory
from .procedural import ProceduralMemory, Procedure
from .semantic import SemanticEntry, SemanticMemory

__all__ = [
    # Base
    "MemoryEntry",
    "MemoryType",
    # Embedding
    "OllamaEmbedder",
    "OllamaEmbeddingError",
    "get_embedder",
    "set_embedder",
    # Episodic
    "EpisodicEntry",
    "EpisodicMemory",
    # Semantic
    "SemanticEntry",
    "SemanticMemory",
    # Procedural
    "Procedure",
    "ProceduralMemory",
]
