"""Knowledge graph - entities and their relationships."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


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

    def add_entity(self, name: str, entity_type: EntityType, properties: dict | None = None) -> Entity:
        """Add an entity to the graph."""
        entity = Entity(
            id=f"{entity_type.value}_{name.lower().replace(' ', '_')}",
            name=name,
            entity_type=entity_type,
            properties=properties or {},
        )
        self._entities[entity.id] = entity
        return entity

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
        return rel

    def query(self, entity_name: str | None = None, relationship_type: RelationshipType | None = None) -> list[Entity | Relationship]:
        """Query the knowledge graph."""
        return []

    def expand(self, entity_id: str, depth: int = 1) -> list[tuple[Entity, Relationship]]:
        """Expand from an entity to connected entities."""
        return []

    def load(self) -> None:
        """Load graph data from SQLite database (no-op if db_path not set).

        Note: This is a stub for compatibility with test infrastructure.
        Full KG persistence via SQLite will be implemented separately.
        """
        # No-op: KG uses in-memory storage only for now.
        # When full SQLite persistence is added, this will load _entities
        # and _relationships from the database.
        pass

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get an entity by ID."""
        return self._entities.get(entity_id)

    def get_relationships(self, entity_id: str) -> list[Relationship]:
        """Get all relationships involving an entity."""
        return [
            r for r in self._relationships.values()
            if r.from_entity_id == entity_id or r.to_entity_id == entity_id
        ]

    def semantic_search(self, query: str, top_k: int = 5) -> list[tuple[Entity, float]]:
        """Simple substring search over entity names (fallback when no embedding engine)."""
        query_lower = query.lower()
        results = []
        for entity in self._entities.values():
            score = 0.0
            if query_lower in entity.name.lower():
                score = 1.0
            elif any(query_lower in p.lower() for p in entity.properties.values() if isinstance(p, str)):
                score = 0.5
            if score > 0:
                results.append((entity, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
