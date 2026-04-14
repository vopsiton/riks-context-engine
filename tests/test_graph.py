"""Tests for knowledge graph module."""

import pytest

from riks_context_engine.graph.knowledge_graph import (
    Entity,
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

    def test_query_by_name(self):
        kg = KnowledgeGraph()
        kg.add_entity("Vahit", EntityType.PERSON)
        kg.add_entity("Vahid", EntityType.PERSON)
        kg.add_entity("Rik", EntityType.CONCEPT)
        results = kg.query(entity_name="Vahit")
        assert len(results) == 1
        assert results[0].name == "Vahit"

    def test_query_by_relationship_type(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        kg = KnowledgeGraph(db_path)
        e1 = kg.add_entity("Vahit", EntityType.PERSON)
        e2 = kg.add_entity("Rik", EntityType.CONCEPT)
        kg.relate(e1, e2, RelationshipType.WORKS_WITH)
        results = kg.query(relationship_type=RelationshipType.WORKS_WITH)
        assert len(results) == 1

    def test_expand(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        kg = KnowledgeGraph(db_path)
        e1 = kg.add_entity("Vahit", EntityType.PERSON)
        e2 = kg.add_entity("Rik", EntityType.CONCEPT)
        kg.relate(e1, e2, RelationshipType.WORKS_WITH)
        expanded = kg.expand(e1.id)
        assert len(expanded) == 1
        assert expanded[0][0].name == "Rik"

    def test_find_path(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        kg = KnowledgeGraph(db_path)
        e1 = kg.add_entity("A", EntityType.CONCEPT)
        e2 = kg.add_entity("B", EntityType.CONCEPT)
        e3 = kg.add_entity("C", EntityType.CONCEPT)
        kg.relate(e1, e2, RelationshipType.RELATED_TO)
        kg.relate(e2, e3, RelationshipType.RELATED_TO)
        path = kg.find_path(e1.id, e3.id)
        assert path is not None
        assert len(path) == 2

    def test_get_entity(self):
        kg = KnowledgeGraph()
        e1 = kg.add_entity("Vahit", EntityType.PERSON)
        found = kg.get_entity(e1.id)
        assert found is not None
        assert found.name == "Vahit"

    def test_get_relationships(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        kg = KnowledgeGraph(db_path)
        e1 = kg.add_entity("Vahit", EntityType.PERSON)
        e2 = kg.add_entity("Rik", EntityType.CONCEPT)
        kg.relate(e1, e2, RelationshipType.WORKS_WITH)
        rels = kg.get_relationships(e1.id)
        assert len(rels) == 1
