## Summary

Implements Memory Export/Import for cross-model portability (issue #36).

### What was done

**src/riks_context_engine/memory/export.py** — Core export/import logic
- ExportManifest dataclass with schema versioning (v1.0)
- export_memory() — selective export by type/date range/tags
- dump_manifest() / parse_manifest() — JSON and YAML serialization
- import_to_memory() — import with merge/replace semantics

**src/riks_context_engine/api/server.py** — API endpoints
- GET /api/v1/memory/export — export with filters (types, date_from, date_to, tags, format)
- POST /api/v1/memory/import — import from JSON/YAML manifest (merge or replace)
- Lifespan now initializes module-level memory instances (episodic, semantic, procedural)

**tests/test_export.py** — 12 test cases (all passing)
- Export all tiers / filter by type / filter by date range
- JSON and YAML round-trip
- Schema version compatibility check
- Import merge (skip duplicates) and replace (clear then import) for all tiers

### Dependencies
- Added pyyaml>=6.0 to pyproject.toml

### Test results
- 102 tests pass (test_api and test_context have pre-existing import errors on master — not related to this PR)
