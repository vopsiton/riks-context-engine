"""Tests for knowledge graph module."""

from riks_context_engine.graph.knowledge_graph import (
    EntityType,
    KnowledgeGraph,
    RelationshipType,
)


class TestKnowledgeGraph:
    def test_init(self):
        kg = KnowledgeGraph()
        assert len(kg._entities) == 0
        assert len(kg._relationships) == 0

    def test_add_entity(self):
        kg = KnowledgeGraph()
        vahit = kg.add_entity("Vahit", EntityType.PERSON, {"role": "DevSecOps Lead"})
        assert vahit.name == "Vahit"
        assert vahit.entity_type == EntityType.PERSON
        assert vahit.properties["role"] == "DevSecOps Lead"

    def test_relate_entities(self):
        kg = KnowledgeGraph()
        vahit = kg.add_entity("Vahit", EntityType.PERSON)
        opsiton = kg.add_entity("Opsiton", EntityType.PROJECT)
        rel = kg.relate(vahit, opsiton, RelationshipType.WORKS_WITH)
        assert rel.from_entity_id == vahit.id
        assert rel.to_entity_id == opsiton.id
        assert rel.relationship_type == RelationshipType.WORKS_WITH

    def test_entity_has_id(self):
        kg = KnowledgeGraph()
        entity = kg.add_entity("Test", EntityType.CONCEPT)
        assert entity.id.startswith("concept_")
