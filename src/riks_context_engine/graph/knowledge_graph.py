"""Knowledge graph - entities and their relationships with semantic search."""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import sqrt
from pathlib import Path
from typing import Any, Protocol

from riks_context_engine.memory.embedding import get_embedder


class EmbedderProtocol(Protocol):
    """Protocol for embedding services."""

    def embed(self, text: str) -> Any: ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EntityType(Enum):
    PERSON = "person"
    PROJECT = "project"
    CONCEPT = "concept"
    EVENT = "event"
    TOOL = "tool"
    DOCUMENT = "document"


class RelationshipType(Enum):
    WORKS_WITH = "works_with"
    DEPENDS_ON = "depends_on"
    USES = "uses"
    PARTICIPATED_IN = "participated_in"
    KNOWS_ABOUT = "knows_about"
    RELATED_TO = "related_to"


@dataclass
class Entity:
    """A graph entity."""

    id: str
    name: str
    entity_type: EntityType
    properties: dict = field(default_factory=dict)
    created_at: datetime = datetime.now(timezone.utc)
    last_updated: datetime = datetime.now(timezone.utc)


@dataclass
class Relationship:
    """A relationship between two entities."""

    id: str
    from_entity_id: str
    to_entity_id: str
    relationship_type: RelationshipType
    properties: dict = field(default_factory=dict)
    confidence: float = 1.0
    created_at: datetime = datetime.now(timezone.utc)


class KnowledgeGraph:
    """Graph database for entities and relationships.

    Enables queries like "Who was in that meeting?" or
    "What do I know about Kubernetes?" through entity expansion
    and relationship traversal.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or "data/knowledge_graph.db"
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite database for persistence."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                last_updated TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                from_entity_id TEXT NOT NULL,
                to_entity_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (from_entity_id) REFERENCES entities(id),
                FOREIGN KEY (to_entity_id) REFERENCES entities(id)
            );
            CREATE INDEX IF NOT EXISTS idx_rels_from ON relationships(from_entity_id);
            CREATE INDEX IF NOT EXISTS idx_rels_to ON relationships(to_entity_id);
            CREATE INDEX IF NOT EXISTS idx_rels_type ON relationships(relationship_type);
        """)
        conn.close()

    def load(self) -> None:
        """Load entities and relationships from SQLite (call after init)."""
        self._load_from_db()

    def _load_from_db(self) -> None:
        """Load entities and relationships from SQLite."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for row in cur.execute("SELECT * FROM entities"):
            entity = Entity(
                id=row["id"],
                name=row["name"],
                entity_type=EntityType(row["entity_type"]),
                properties=json.loads(row["properties"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                last_updated=datetime.fromisoformat(row["last_updated"]),
            )
            self._entities[entity.id] = entity

        for row in cur.execute("SELECT * FROM relationships"):
            rel = Relationship(
                id=row["id"],
                from_entity_id=row["from_entity_id"],
                to_entity_id=row["to_entity_id"],
                relationship_type=RelationshipType(row["relationship_type"]),
                properties=json.loads(row["properties"]),
                confidence=row["confidence"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            self._relationships[rel.id] = rel

        conn.close()

    def add_entity(
        self, name: str, entity_type: EntityType, properties: dict | None = None
    ) -> Entity:
        """Add an entity to the graph."""
        entity = Entity(
            id=f"{entity_type.value}_{name.lower().replace(' ', '_')}",
            name=name,
            entity_type=entity_type,
            properties=properties or {},
        )
        self._entities[entity.id] = entity
        self._save_entity_to_db(entity)
        return entity

    def _save_entity_to_db(self, entity: Entity) -> None:
        """Persist entity to SQLite."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO entities (id, name, entity_type, properties, created_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entity.id,
                entity.name,
                entity.entity_type.value,
                json.dumps(entity.properties),
                entity.created_at.isoformat(),
                entity.last_updated.isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def relate(
        self,
        from_entity: Entity,
        to_entity: Entity,
        relationship_type: RelationshipType,
        confidence: float = 1.0,
    ) -> Relationship:
        """Create a relationship between two entities."""
        rel = Relationship(
            id=f"rel_{from_entity.id}_{relationship_type.value}_{to_entity.id}",
            from_entity_id=from_entity.id,
            to_entity_id=to_entity.id,
            relationship_type=relationship_type,
            confidence=confidence,
        )
        self._relationships[rel.id] = rel
        self._save_rel_to_db(rel)
        return rel

    def _save_rel_to_db(self, rel: Relationship) -> None:
        """Persist relationship to SQLite."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO relationships (id, from_entity_id, to_entity_id, relationship_type, properties, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rel.id,
                rel.from_entity_id,
                rel.to_entity_id,
                rel.relationship_type.value,
                json.dumps(rel.properties),
                rel.confidence,
                rel.created_at.isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def query(
        self, entity_name: str | None = None, relationship_type: RelationshipType | None = None
    ) -> list[Entity | Relationship]:
        """Query the knowledge graph by entity name or relationship type.

        Args:
            entity_name: Filter entities by name (partial match supported)
            relationship_type: Filter by type of relationships

        Returns:
            List of matching entities and/or relationships
        """
        results: list[Entity | Relationship] = []

        if entity_name:
            name_lower = entity_name.lower()
            for entity in self._entities.values():
                if name_lower in entity.name.lower():
                    results.append(entity)

        if relationship_type:
            for rel in self._relationships.values():
                if rel.relationship_type == relationship_type:
                    results.append(rel)

        if not entity_name and not relationship_type:
            # Return all if no filter specified
            results = list(self._entities.values()) + list(self._relationships.values())

        return results

    def expand(self, entity_id: str, depth: int = 1) -> list[tuple[Entity, Relationship]]:
        """Expand from an entity to connected entities.

        Args:
            entity_id: Starting entity ID
            depth: Traversal depth (1 = direct connections only)

        Returns:
            List of (connected_entity, relationship) tuples
        """
        if entity_id not in self._entities:
            return []

        results: list[tuple[Entity, Relationship]] = []
        visited: set[str] = {entity_id}
        queue: list[tuple[str, int]] = [(entity_id, 0)]

        while queue:
            current_id, current_depth = queue.pop(0)

            if current_depth >= depth:
                continue

            for rel in self._relationships.values():
                neighbor_id: str | None = None

                if rel.from_entity_id == current_id and rel.to_entity_id not in visited:
                    neighbor_id = rel.to_entity_id
                elif rel.to_entity_id == current_id and rel.from_entity_id not in visited:
                    neighbor_id = rel.from_entity_id

                if neighbor_id and neighbor_id in self._entities:
                    visited.add(neighbor_id)
                    results.append((self._entities[neighbor_id], rel))
                    queue.append((neighbor_id, current_depth + 1))

        return results

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get a single entity by ID."""
        return self._entities.get(entity_id)

    def get_relationships(self, entity_id: str) -> list[Relationship]:
        """Get all relationships for an entity."""
        return [
            rel
            for rel in self._relationships.values()
            if rel.from_entity_id == entity_id or rel.to_entity_id == entity_id
        ]

    def find_path(
        self, from_entity_id: str, to_entity_id: str, max_depth: int = 3
    ) -> list[Relationship] | None:
        """Find a path between two entities using BFS.


        Args:
            from_entity_id: Start entity ID
            to_entity_id: Target entity ID
            max_depth: Maximum path length

        Returns:
            List of relationships forming the path, or None if no path found
        """
        if from_entity_id == to_entity_id:
            return []

        visited: set[str] = {from_entity_id}
        queue: list[tuple[str, list[Relationship]]] = [(from_entity_id, [])]

        while queue:
            current_id, path = queue.pop(0)

            if len(path) >= max_depth:
                continue

            for rel in self._relationships.values():
                if rel.from_entity_id == current_id and rel.to_entity_id not in visited:
                    new_path = path + [rel]
                    if rel.to_entity_id == to_entity_id:
                        return new_path
                    visited.add(rel.to_entity_id)
                    queue.append((rel.to_entity_id, new_path))

                elif rel.to_entity_id == current_id and rel.from_entity_id not in visited:
                    new_path = path + [rel]
                    if rel.from_entity_id == to_entity_id:
                        return new_path
                    visited.add(rel.from_entity_id)
                    queue.append((rel.from_entity_id, new_path))

        return None

    # ── Semantic Search ────────────────────────────────────────────────────

    def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        embedder: EmbedderProtocol | None = None,
        score_threshold: float = 0.0,
    ) -> list[tuple[Entity, float]]:
        """Find entities most similar to a natural language query.

        Args:
            query: Natural language search phrase
            top_k: Maximum number of results to return
            embedder: Embedding service (defaults to OllamaEmbedder)
            score_threshold: Minimum cosine similarity score (0.0–1.0)

        Returns:
            List of (entity, similarity_score) tuples, sorted descending
        """
        if not self._entities:
            return []

        emb_service = embedder or get_embedder()

        try:
            query_emb = emb_service.embed(query)
            if hasattr(query_emb, "embedding"):
                query_vec = query_emb.embedding
            else:
                query_vec = query_emb  # fallback for raw list responses
        except Exception:
            # If embedding service unavailable, fall back to keyword match
            return self._keyword_search(query, top_k)

        scored: list[tuple[Entity, float]] = []
        for entity in self._entities.values():
            entity_vec = self._get_entity_embedding(entity)
            if entity_vec is not None:
                score = _cosine_similarity(query_vec, entity_vec)
                if score >= score_threshold:
                    scored.append((entity, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _get_entity_embedding(self, entity: Entity) -> list[float] | None:
        """Get cached embedding vector for an entity, computing if needed."""
        cache_key = f"_emb_{entity.id}"
        if hasattr(self, cache_key):
            return getattr(self, cache_key)

        # Build descriptive text from entity properties
        parts = [entity.name]
        parts.append(entity.entity_type.value)
        parts.extend(f"{k}={v}" for k, v in entity.properties.items())
        text = ", ".join(parts)

        try:
            result = get_embedder().embed(text)
            vec = result.embedding if hasattr(result, "embedding") else result
            setattr(self, cache_key, vec)
            return vec
        except Exception:
            return None

    def _keyword_search(self, query: str, top_k: int) -> list[tuple[Entity, float]]:
        """Fuzzy fallback when semantic search is unavailable."""
        q = query.lower()
        results: list[tuple[Entity, float]] = []
        for entity in self._entities.values():
            score = 0.0
            if q in entity.name.lower():
                score = 1.0
            elif any(q in str(v).lower() for v in entity.properties.values()):
                score = 0.5
            if score > 0:
                results.append((entity, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
