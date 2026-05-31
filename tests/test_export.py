"""Tests for memory export/import (issue #36)."""

import json
import os
import tempfile

import pytest

from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.export import (
    SCHEMA_VERSION,
    dump_manifest,
    export_memory,
    import_to_memory,
    parse_manifest,
)
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory


def _temp_json_path():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    path = f.name
    f.close()
    return path


def _temp_db_path():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = f.name
    f.close()
    os.unlink(path)
    return path


class TestExportMemory:
    def test_export_all_tiers(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("test observation", importance=0.9, tags=["test"])

        sm = SemanticMemory(db_path=_temp_db_path())
        sm.add("Rik", "is", "an AI assistant", confidence=0.95)

        pm = ProceduralMemory(storage_path=_temp_json_path())
        pm.store("Deploy Service", "Deploy to Kubernetes", ["build", "push", "apply"])

        manifest = export_memory(ep, sm, pm)

        assert manifest.metadata.schema_version == SCHEMA_VERSION
        assert len(manifest.episodic) == 1
        assert manifest.episodic[0]["content"] == "test observation"
        assert len(manifest.semantic) == 1
        assert manifest.semantic[0]["subject"] == "Rik"
        assert len(manifest.procedural) == 1
        assert manifest.procedural[0]["name"] == "Deploy Service"

    def test_export_filter_by_type(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("ep1")

        sm = SemanticMemory(db_path=_temp_db_path())
        sm.add("s1", "p1", "o1")

        manifest = export_memory(ep, sm, None, include_types=["episodic"])
        assert len(manifest.episodic) == 1
        assert len(manifest.semantic) == 0

    def test_export_filter_by_date_range(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("old entry")

        from datetime import datetime, timezone
        manifest = export_memory(ep, None, None, date_from=datetime.now(timezone.utc))
        assert len(manifest.episodic) == 0

    def test_export_empty_tiers(self):
        manifest = export_memory(None, None, None)
        assert manifest.episodic == []
        assert manifest.semantic == []
        assert manifest.procedural == []


class TestDumpAndParse:
    def test_json_round_trip(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("round trip test", tags=["test"])

        sm = SemanticMemory(db_path=_temp_db_path())
        sm.add("subject", "predicate", "object")

        pm = ProceduralMemory(storage_path=_temp_json_path())
        pm.store("Proc", "desc", ["step"])

        manifest = export_memory(ep, sm, pm)
        json_str = dump_manifest(manifest, "json")
        parsed = parse_manifest(json_str, "json")

        assert parsed.metadata.schema_version == SCHEMA_VERSION
        assert len(parsed.episodic) == 1
        assert len(parsed.semantic) == 1
        assert len(parsed.procedural) == 1

    def test_yaml_round_trip(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("yaml test")

        sm = SemanticMemory(db_path=_temp_db_path())
        sm.add("subj", "pred", "obj")

        manifest = export_memory(ep, sm, None)
        yaml_str = dump_manifest(manifest, "yaml")
        parsed = parse_manifest(yaml_str, "yaml")

        assert len(parsed.episodic) == 1
        assert len(parsed.semantic) == 1

    def test_schema_version_check_rejects_mismatched(self):
        bad_data = {
            "metadata": {"schema_version": "99.0", "exported_at": "2026-01-01T00:00:00Z", "tool": "test", "export_id": "abc"},
            "episodic": [],
            "semantic": [],
            "procedural": [],
        }
        with pytest.raises(ValueError, match="Schema version mismatch"):
            parse_manifest(json.dumps(bad_data), "json")

    def test_parse_rejects_non_object(self):
        with pytest.raises(ValueError, match="Expected object"):
            parse_manifest("[]", "json")


class TestImportToMemory:
    def test_import_merge_skips_duplicates(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("existing entry")

        ep2 = EpisodicMemory(storage_path=_temp_json_path())
        ep2.add("new entry")

        manifest = export_memory(ep2, None, None)
        imported = import_to_memory(manifest, ep, None, None, merge=True)

        assert imported["episodic"] == 1
        assert len(ep.entries) == 2

    def test_import_replace_clears_existing(self):
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("to be replaced")

        ep2 = EpisodicMemory(storage_path=_temp_json_path())
        ep2.add("new entry")

        manifest = export_memory(ep2, None, None)
        imported = import_to_memory(manifest, ep, None, None, merge=False)

        assert imported["episodic"] == 1
        assert len(ep.entries) == 1
        assert list(ep.entries.values())[0].content == "new entry"

    def test_import_semantic(self):
        sm_src = SemanticMemory(db_path=_temp_db_path())
        sm_src.add("source", "predicate", "object")

        dest = SemanticMemory(db_path=_temp_db_path())
        manifest = export_memory(None, sm_src, None)
        imported = import_to_memory(manifest, None, dest, None, merge=True)

        assert imported["semantic"] == 1
        assert len(dest) == 1

    def test_import_procedural(self):
        pm_src = ProceduralMemory(storage_path=_temp_json_path())
        pm_src.store("Test Proc", "A test procedure", ["step1", "step2"])

        dest = ProceduralMemory(storage_path=_temp_json_path())
        manifest = export_memory(None, None, pm_src)
        imported = import_to_memory(manifest, None, None, dest, merge=True)

        assert imported["procedural"] == 1
        assert len(dest) == 1
        assert list(dest.procedures.values())[0].name == "Test Proc"
