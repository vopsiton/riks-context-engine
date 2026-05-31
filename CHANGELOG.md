# Changelog

All notable changes to **Rik Context Engine** will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-05-31

### Added
- **`feat(context)`: Semantic Summarization** — LLM-generated compression of TIER_3 messages to ≤20% token count while preserving key facts, decisions, and intent ([#86](https://github.com/vopsiton/riks-context-engine/issues/86))
  - `SemanticSummarizer` class with `summarize_tier3()`, `SummarizedBlock` dataclass
  - Keyword-extraction fallback when LLM unavailable
  - `set_summarizer()` / `run_summarization()` integrated into `ContextWindowManager`
- **`feat(context)`: Priority Inheritance** — Child messages inherit parent importance; thread coherence scoring via `get_thread_coherence()` ([#94](https://github.com/vopsiton/riks-context-engine/issues/94))
- **`docs`: PR Template & Code Review Checklist** — Enforced PR description format with logic/style/security/testing checklist ([#92](https://github.com/vopsiton/riks-context-engine/issues/92))

---

## [0.2.1] - 2026-05-31

### Fixed
- **`fix(version)`: `__version__` alignment** — `__init__.py` declared `0.1.0` but `pyproject.toml` declared `0.2.0`. Updated `__version__` to `0.2.0` for consistency across package and CLI ([opsiton-team#cron-2026-05-31])

### Added
- **`feat(context)`: Coherence validation** — `validate_coherence()` and `get_coherence_score()` methods for measuring and validating context window coherence ([#85](https://github.com/vopsiton/riks-context-engine/pull/85))
- **`feat(memory)`: JSON/YAML export/import** — Full memory portability across models and sessions ([#36](https://github.com/vopsiton/riks-context-engine/issues/36))
  - `export_memory()` — selective export by type, date range, and tags
  - `dump_manifest()` / `parse_manifest()` — JSON and YAML serialization
  - `import_to_memory()` — merge or replace semantics with schema version validation
  - REST endpoints: `GET /api/v1/memory/export`, `POST /api/v1/memory/import`
- **`feat(context)`: Context window persistence** — `save()`/`load()` for context across restarts with auto-save ([#36](https://github.com/vopsiton/riks-context-engine/issues/36))
- **`docs`: MCP Server feature spec** — Model Context Protocol integration blueprint ([#34](https://github.com/vopsiton/riks-context-engine/issues/34))
- **181 test cases** for export/import round-trips, schema validation, merge/replace

### Fixed
- **`fix(kg)`**: Explicit `strict=True` in `zip()` in `_cosine_similarity` (Ruff B905 — prevents silent truncation on mismatched vector lengths)
- **`fix`: Multiple production bugs** — Various bug fixes discovered during test runs ([#82](https://github.com/vopsiton/riks-context-engine/pull/82))

### Dependencies
- Added `pyyaml>=6.0`

---

## [0.2.0] - 2026-04-18

### Added
- **Tool Calling Abstraction Layer** — Structured tool definitions, adapters, and execution framework
- **Full CI/CD Pipeline** — GitHub Actions with pre-commit, ruff, mypy, pytest, Docker build/push
- **FastAPI Server + Web UI** — Interactive chat interface at `GET /`
- **Security Policy** — `SECURITY.md` with vulnerability disclosure process
- **`fix(docker)`: Non-root user** — Runs as `riks` user, binds to localhost only

### Changed
- **Docker image**: Multi-stage build, non-root execution, `uv` for dependency management
- **Ruff configuration** aligned across CI, pre-commit, and dev dependencies

### Fixed
- Pre-commit `F841` (unused variable) errors in `test_context.py`
- Remaining `UP045`, `UP035`, `I001` lint errors across codebase
- Missing API dependencies and `:memory:` storage bug
- Regex error in context manager

---

## [0.1.0] - 2026-04-12

### Added
- 3-tier memory architecture (Episodic, Semantic, Procedural)
- Intelligent Context Window Manager with importance-based pruning
- Knowledge Graph with semantic vector search (Ollama embeddings)
- Task Decomposer with dependency resolution
- Self-Reflection Analyzer for learning from mistakes
- Docker sandbox environment for local testing
