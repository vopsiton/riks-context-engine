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
            "metadata": {
                "schema_version": "99.0",
                "exported_at": "2026-01-01T00:00:00Z",
                "tool": "test",
                "export_id": "abc",
            },
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


class TestExportFiltersExtended:
    """Lines 66, 132, 139, 146, 148: additional filter coverage."""

    def test_export_date_to_excludes_entries_after_cutoff(self):
        """Line 66: date_to branch in _entry_in_date_range returns False."""
        from datetime import datetime, timezone

        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("recent entry", tags=["test"])

        # date_to set to far past → entry is after cutoff → excluded
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        manifest = export_memory(ep, None, None, date_to=past)
        assert len(manifest.episodic) == 0

    def test_export_episodic_tags_filter_excludes_non_matching(self):
        """Line 132: episodic tags filter skips entries without matching tag."""
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("tagged entry", tags=["important"])
        ep.add("other entry", tags=["noise"])

        manifest = export_memory(ep, None, None, tags=["important"])
        assert len(manifest.episodic) == 1
        assert manifest.episodic[0]["content"] == "tagged entry"

    def test_export_semantic_date_range_excludes_entries(self):
        """Line 139: semantic entries outside date_from are excluded."""
        from datetime import datetime, timezone

        sm = SemanticMemory(db_path=_temp_db_path())
        sm.add("s", "p", "o")

        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        manifest = export_memory(None, sm, None, date_from=future)
        assert len(manifest.semantic) == 0

    def test_export_procedural_date_range_excludes_entries(self):
        """Line 146: procedural entries outside date_from are excluded."""
        from datetime import datetime, timezone

        pm = ProceduralMemory(storage_path=_temp_json_path())
        pm.store("Proc", "desc", ["step1"])

        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        manifest = export_memory(None, None, pm, date_from=future)
        assert len(manifest.procedural) == 0

    def test_export_procedural_tags_filter_excludes_non_matching(self):
        """Line 148: procedural tags filter skips non-matching entries."""
        pm = ProceduralMemory(storage_path=_temp_json_path())
        pm.store("Tagged Proc", "desc", ["step1"], tags=["deploy"])
        pm.store("Other Proc", "desc", ["step1"], tags=["test"])

        manifest = export_memory(None, None, pm, tags=["deploy"])
        assert len(manifest.procedural) == 1
        assert manifest.procedural[0]["name"] == "Tagged Proc"


class TestDumpManifestToFile:
    """Lines 168-169: dump_manifest writes to disk when path is provided."""

    def test_dump_manifest_json_to_file(self):
        """Lines 168-169: JSON manifest written to disk."""
        from pathlib import Path

        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("file export test")
        manifest = export_memory(ep, None, None)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = Path(f.name)
        try:
            content = dump_manifest(manifest, "json", path=out_path)
            assert out_path.exists()
            assert out_path.read_text(encoding="utf-8") == content
            assert "file export test" in content
        finally:
            out_path.unlink(missing_ok=True)

    def test_dump_manifest_yaml_to_file(self):
        """Lines 168-169: YAML manifest written to disk."""
        from pathlib import Path

        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("yaml file test")
        manifest = export_memory(ep, None, None)

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            out_path = Path(f.name)
        try:
            dump_manifest(manifest, "yaml", path=out_path)
            assert out_path.exists()
            assert "yaml file test" in out_path.read_text(encoding="utf-8")
        finally:
            out_path.unlink(missing_ok=True)


class TestParseManifestValidationExtended:
    """Lines 182, 184, 187, 190: parse_manifest validation error branches."""

    def test_parse_missing_metadata_raises(self):
        """Line 182: manifest without 'metadata' raises ValueError."""
        bad = json.dumps({"episodic": [], "semantic": [], "procedural": []})
        with pytest.raises(ValueError, match="Missing required 'metadata'"):
            parse_manifest(bad, "json")

    def test_parse_non_dict_metadata_raises(self):
        """Line 184: metadata that is not a dict raises ValueError."""
        bad = json.dumps(
            {"metadata": "just a string", "episodic": [], "semantic": [], "procedural": []}
        )
        with pytest.raises(ValueError, match="Expected 'metadata' to be an object"):
            parse_manifest(bad, "json")

    def test_parse_missing_schema_version_raises(self):
        """Line 187: metadata without schema_version raises ValueError."""
        bad = json.dumps(
            {
                "metadata": {
                    "exported_at": "2026-01-01T00:00:00Z",
                    "tool": "test",
                    "export_id": "abc",
                },
                "episodic": [],
                "semantic": [],
                "procedural": [],
            }
        )
        with pytest.raises(ValueError, match="Missing required 'schema_version'"):
            parse_manifest(bad, "json")

    def test_parse_null_schema_version_raises(self):
        """Line 190: schema_version = None raises ValueError."""
        bad = json.dumps(
            {
                "metadata": {
                    "schema_version": None,
                    "exported_at": "2026-01-01T00:00:00Z",
                    "tool": "test",
                    "export_id": "abc",
                },
                "episodic": [],
                "semantic": [],
                "procedural": [],
            }
        )
        with pytest.raises(ValueError, match="Missing required 'schema_version'"):
            parse_manifest(bad, "json")


class TestImportEdgeCases:
    """Lines 252, 260-262, 266, 269, 277-279, 284: import edge cases."""

    def test_import_episodic_merge_skips_duplicate_ids(self):
        """Line 252: episodic merge mode skips entries with existing IDs."""
        ep = EpisodicMemory(storage_path=_temp_json_path())
        ep.add("original entry")
        original_count = len(ep.entries)

        # Export from the same memory, then re-import → all IDs already present
        manifest = export_memory(ep, None, None)
        imported = import_to_memory(manifest, ep, None, None, merge=True)

        assert imported["episodic"] == 0
        assert len(ep.entries) == original_count

    def test_import_semantic_replace_clears_existing(self):
        """Lines 260-262: semantic replace mode deletes existing before import."""
        sm_existing = SemanticMemory(db_path=_temp_db_path())
        sm_existing.add("old_subject", "old_pred", "old_obj")

        sm_src = SemanticMemory(db_path=_temp_db_path())
        sm_src.add("new_subject", "new_pred", "new_obj")

        manifest = export_memory(None, sm_src, None)
        imported = import_to_memory(manifest, None, sm_existing, None, merge=False)

        assert imported["semantic"] == 1
        results = sm_existing.query()
        assert len(results) == 1
        assert results[0].subject == "new_subject"

    def test_import_semantic_merge_skips_duplicate_ids(self):
        """Lines 266, 269: semantic merge builds existing_ids and skips duplicates."""
        sm = SemanticMemory(db_path=_temp_db_path())
        sm.add("existing_subject", "pred", "obj")
        count_before = len(sm)

        # Export then re-import in merge mode → IDs already exist → 0 imported
        manifest = export_memory(None, sm, None)
        imported = import_to_memory(manifest, None, sm, None, merge=True)

        assert imported["semantic"] == 0
        assert len(sm) == count_before

    def test_import_procedural_replace_clears_existing(self):
        """Lines 277-279: procedural replace mode deletes existing entries."""
        pm_existing = ProceduralMemory(storage_path=_temp_json_path())
        pm_existing.store("Old Proc", "old desc", ["old_step"])

        pm_src = ProceduralMemory(storage_path=_temp_json_path())
        pm_src.store("New Proc", "new desc", ["new_step"])

        manifest = export_memory(None, None, pm_src)
        imported = import_to_memory(manifest, None, None, pm_existing, merge=False)

        assert imported["procedural"] == 1
        assert len(pm_existing.procedures) == 1
        assert list(pm_existing.procedures.values())[0].name == "New Proc"

    def test_import_procedural_merge_skips_duplicate_ids(self):
        """Line 284: procedural merge mode skips entries with existing IDs."""
        pm = ProceduralMemory(storage_path=_temp_json_path())
        pm.store("Existing Proc", "desc", ["step1"])
        count_before = len(pm.procedures)

        # Export then re-import in merge mode → IDs already exist → 0 imported
        manifest = export_memory(None, None, pm)
        imported = import_to_memory(manifest, None, None, pm, merge=True)

        assert imported["procedural"] == 0
        assert len(pm.procedures) == count_before
