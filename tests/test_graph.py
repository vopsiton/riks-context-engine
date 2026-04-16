"""Tests for knowledge graph module."""

from unittest.mock import MagicMock

import pytest
from riks_context_engine.graph.knowledge_graph import (
    EntityType,
    KnowledgeGraph,
    RelationshipType,
    _cosine_similarity,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1.0, 1.0], [-1.0, -1.0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_empty_vector(self):
        assert _cosine_similarity([], []) == 0.0


class TestKnowledgeGraph:
    def test_init(self):
        # Use in-memory DB to avoid leftover data from previous runs
        kg = KnowledgeGraph(db_path=":memory:")
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


class TestKnowledgeGraphEmbedding:
    """Tests for embedding integration in KnowledgeGraph."""

    def _mock_embedder(self, texts_to_embeddings: dict[str, list[float]]):
        """Create a mock embedder that returns predefined embeddings."""
        mock = MagicMock()
        mock.embed.side_effect = lambda text: MagicMock(
            embedding=texts_to_embeddings.get(text, [0.0] * 10),
            model="nomic-embed-text",
            prompt_tokens=5,
        )
        return mock

    def test_add_entity_generates_embedding(self):
        embedder = self._mock_embedder({"Vahit": [0.1] * 10})
        kg = KnowledgeGraph(embedder=embedder)
        entity = kg.add_entity("Vahit", EntityType.PERSON)
        assert entity.embedding is not None
        assert entity.embedding == [0.1] * 10
        embedder.embed.assert_called_once_with("Vahit")

    def test_add_entity_no_embedder(self):
        kg = KnowledgeGraph()
        entity = kg.add_entity("Vahit", EntityType.PERSON)
        assert entity.embedding is None

    def test_add_entity_auto_embed_false(self):
        embedder = self._mock_embedder({"Vahit": [0.1] * 10})
        kg = KnowledgeGraph(embedder=embedder)
        entity = kg.add_entity("Vahit", EntityType.PERSON, auto_embed=False)
        assert entity.embedding is None

    def test_find_similar_returns_ranked_results(self):
        # Use fully orthogonal unit vectors for clean similarity scores
        # Vahit query: [1,0,0], Vahit entity: [1,0,0] -> cos_sim = 1.0
        # Rik entity: [0,1,0] -> cos_sim = 0.0
        # Opsiton entity: [0,0,1] -> cos_sim = 0.0
        def embed_side_effect(text):
            emb_map = {
                "Vahit": [1.0, 0.0, 0.0],
                "Rik": [0.0, 1.0, 0.0],
                "Opsiton": [0.0, 0.0, 1.0],
            }
            return MagicMock(embedding=emb_map.get(text, [0.0] * 3), model="test", prompt_tokens=1)
        embedder = MagicMock()
        embedder.embed.side_effect = embed_side_effect

        kg = KnowledgeGraph(embedder=embedder)
        kg.add_entity("Vahit", EntityType.PERSON)
        kg.add_entity("Rik", EntityType.CONCEPT)
        kg.add_entity("Opsiton", EntityType.PROJECT)

        results = kg.find_similar("Vahit", top_k=3)
        assert len(results) == 1
        assert results[0][0].name == "Vahit"
        assert results[0][1] == pytest.approx(1.0)

    def test_find_similar_no_embedder(self):
        kg = KnowledgeGraph()
        kg.add_entity("Vahit", EntityType.PERSON)
        results = kg.find_similar("Vahit")
        assert results == []

    def test_find_similar_respects_min_score(self):
        # Vahit: [1,0], Rik: [0,1] -> orthogonal, cos_sim = 0
        # Vahit query: [1,0] -> Vahit entity cos_sim = 1.0, Rik entity cos_sim = 0.0
        def embed_side_effect(text):
            emb_map = {
                "Vahit": [1.0, 0.0],
                "Rik": [0.0, 1.0],
            }
            return MagicMock(embedding=emb_map.get(text, [0.0] * 2), model="test", prompt_tokens=1)
        embedder = MagicMock()
        embedder.embed.side_effect = embed_side_effect

        kg = KnowledgeGraph(embedder=embedder)
        kg.add_entity("Vahit", EntityType.PERSON)
        kg.add_entity("Rik", EntityType.CONCEPT)

        results = kg.find_similar("Vahit", min_score=0.9)
        assert len(results) == 1
        assert results[0][0].name == "Vahit"

    def test_set_embedder(self):
        kg = KnowledgeGraph()
        embedder = self._mock_embedder({"Vahit": [0.5] * 10})
        kg.set_embedder(embedder)
        entity = kg.add_entity("Vahit", EntityType.PERSON)
        assert entity.embedding is not None

    def test_reembed_entity(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        embedder = self._mock_embedder({
            "Vahit": [0.1] * 5,
            "Vahit Updated": [0.9] * 5,
        })
        kg = KnowledgeGraph(db_path, embedder=embedder)
        e1 = kg.add_entity("Vahit", EntityType.PERSON)
        assert e1.embedding == [0.1] * 5

        # Re-embed with new text
        embedder.embed.side_effect = lambda t: MagicMock(
            embedding=[0.9] * 5 if "Updated" in t else [0.1] * 5,
            model="nomic-embed-text",
        )
        e1.name = "Vahit Updated"
        updated = kg.reembed_entity(e1.id)
        assert updated is not None
        assert updated.embedding == [0.9] * 5

    def test_embedding_persisted_to_db(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        embedder = self._mock_embedder({"Vahit": [0.1] * 5})
        kg1 = KnowledgeGraph(db_path, embedder=embedder)
        kg1.add_entity("Vahit", EntityType.PERSON)

        # Load in new instance — embedding should be restored
        kg2 = KnowledgeGraph(db_path)
        kg2.load()
        assert len(kg2._entities) == 1
        entity = kg2.get_entity("person_vahit")
        assert entity is not None
        assert entity.embedding == [0.1] * 5
