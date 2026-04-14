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

    def query(
        self, entity_name: str | None = None, relationship_type: RelationshipType | None = None
    ) -> list[Entity | Relationship]:
        """Query the knowledge graph."""
        return []

    def expand(self, entity_id: str, depth: int = 1) -> list[tuple[Entity, Relationship]]:
        """Expand from an entity to connected entities."""
        return []
