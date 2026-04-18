# Developer Guide — Rik Context Engine

> Everything you need to start developing, testing, and contributing to Rik Context Engine.

**Audience:** Contributors and extension developers
**Python:** 3.10+
**License:** AGPL-3.0

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development Setup](#local-development-setup)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Code Quality Tools](#code-quality-tools)
- [CI/CD Pipeline](#cicd-pipeline)
- [Contributing Guidelines](#contributing-guidelines)
- [Writing Tests](#writing-tests)
- [Extension Points](#extension-points)
- [Release Process](#release-process)

---

## Prerequisites

- **Python 3.10, 3.11, or 3.12**
- **Git**
- **Ollama** (optional, for embedding services)
- **Docker & Docker Compose** (optional, for containerized development)

---

## Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine
```

### 2. Create and Activate a Virtual Environment

```bash
# Create
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activate (Windows CMD)
venv\Scripts\activate.bat
```

### 3. Install Dependencies

```bash
# Basic dev dependencies
pip install -e ".[dev]"

# With OpenAI provider
pip install -e ".[openai]"

# With Anthropic provider
pip install -e ".[anthropic]"
```

### 4. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your local settings:

```bash
# Required for embedding features
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=gemma4-31b-q4

# Optional: ChromaDB for vector similarity
CHROMA_HOST=localhost

# Data directory (relative to project root)
DATA_DIR=./data
```

### 5. Verify Installation

```bash
python -c "
from riks_context_engine import __version__
from riks_context_engine.memory import EpisodicMemory, SemanticMemory, ProceduralMemory
from riks_context_engine.context import ContextWindowManager
from riks_context_engine.graph import KnowledgeGraph
from riks_context_engine.reflection import ReflectionAnalyzer
print(f'riks-context-engine {__version__}')
print('All modules imported successfully')
"
```

### 6. Install Pre-commit Hooks

```bash
pre-commit install
```

This runs linting, type-checking, and format checks on every commit.

---

## Project Structure

```
riks-context-engine/
├── src/
│   └── riks_context_engine/
│       ├── __init__.py              # Package version
│       ├── memory/
│       │   ├── base.py              # MemoryEntry + MemoryType
│       │   ├── episodic.py          # EpisodicMemory
│       │   ├── semantic.py          # SemanticMemory
│       │   ├── procedural.py        # ProceduralMemory
│       │   ├── embedding.py         # OllamaEmbedder
│       │   └── tier_manager.py      # TierManager
│       ├── context/
│       │   └── manager.py           # ContextWindowManager + ImportanceScorer
│       ├── tasks/
│       │   └── decomposer.py        # TaskDecomposer
│       ├── graph/
│       │   └── knowledge_graph.py   # KnowledgeGraph
│       ├── reflection/
│       │   └── analyzer.py          # ReflectionAnalyzer
│       └── cli/
│           └── main.py              # CLI entry point (`riks`)
├── tests/
│   ├── test_memory.py
│   ├── test_context.py
│   ├── test_graph.py
│   ├── test_reflection.py
│   └── test_decomposer.py
├── docs/                            # This documentation
├── data/                            # Runtime storage (gitignored)
├── pyproject.toml                   # Package + tool configuration
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .pre-commit-config.yaml
└── CONTRIBUTING.md
```

### Module Responsibilities

| Module | Responsibility | Public API |
|--------|---------------|------------|
| `memory/base.py` | Unified `MemoryEntry` schema | `MemoryEntry`, `MemoryType` |
| `memory/episodic.py` | Session-level JSON storage | `EpisodicMemory`, `EpisodicEntry` |
| `memory/semantic.py` | Long-term SQLite triples | `SemanticMemory`, `SemanticEntry` |
| `memory/procedural.py` | Skills/workflows JSON | `ProceduralMemory`, `Procedure` |
| `memory/embedding.py` | Ollama vector generation | `OllamaEmbedder`, `get_embedder()` |
| `memory/tier_manager.py` | Cross-tier promotion/demotion | `TierManager`, `TierConfig` |
| `context/manager.py` | Context window + pruning | `ContextWindowManager`, `ImportanceScorer` |
| `tasks/decomposer.py` | Goal → task graph | `TaskDecomposer`, `Task`, `TaskGraph` |
| `graph/knowledge_graph.py` | Entity-relationship graph | `KnowledgeGraph`, `Entity`, `Relationship` |
| `reflection/analyzer.py` | Self-improvement loop | `ReflectionAnalyzer`, `Lesson`, `ReflectionReport` |

---

## Running Tests

### Run All Tests

```bash
pytest
```

### Run with Coverage Report

```bash
pytest --cov=src/ --cov-report=html --cov-report=term
```

Open `htmlcov/index.html` in a browser to see the detailed coverage report.

### Run Specific Test Files

```bash
pytest tests/test_memory.py
pytest tests/test_context.py
pytest tests/test_graph.py
pytest tests/test_reflection.py
pytest tests/test_decomposer.py
```

### Run Tests Matching a Pattern

```bash
pytest -k "episodic"
pytest -k "semantic"
pytest -k "context"
```

### Run Tests in Parallel

```bash
pytest -n auto
```

Requires `pytest-xdist` (included in `[dev]`).

### Run Tests Against Multiple Python Versions

```bash
# Using tox (if installed)
pip install tox
tox
```

Or test manually:
```bash
python3.10 -m pytest
python3.11 -m pytest
python3.12 -m pytest
```

---

## Code Quality Tools

### Ruff (Linting + Formatting)

```bash
# Lint all source
ruff check src/

# Lint specific file
ruff check src/riks_context_engine/memory/episodic.py

# Auto-fix fixable issues
ruff check src/ --fix
```

Ruff is configured in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py310"
select = ["E", "F", "W", "I", "N", "UP", "B", "C4"]
ignore = ["E501"]  # Line length handled separately
```

### MyPy (Type Checking)

```bash
# Type-check all source
mypy src/

# Type-check specific module
mypy src/riks_context_engine/memory/

# Ignore missing imports (common for optional deps)
mypy src/ --ignore-missing-imports
```

Configuration in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
```

### Pre-commit Hooks

Hooks defined in `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    hooks:
      - id: mypy
```

Run all hooks manually:
```bash
pre-commit run --all-files
```

### Pre-commit on CI

Pre-commit runs on every push and PR in the CI pipeline (see [CI/CD Pipeline](#cicd-pipeline)).

---

## CI/CD Pipeline

### GitHub Actions Workflows

Located in `.github/workflows/`.

#### `ci.yml` — Continuous Integration

Triggers on: every push to `main`/`master` and on all PRs.

```yaml
jobs:
  test:          # Runs on Python 3.10, 3.11, 3.12
    - ruff check
    - mypy type-check
    - pytest --cov (uploads to Codecov)

  pre-commit:     # Runs pre-commit hooks on Python 3.11
```

#### `deploy.yml` — Build and Deploy

Builds Docker image and pushes to GitHub Container Registry (`ghcr.io`).

Triggered on: pushes to `main`/`master`.

Steps:
1. `test` job (must pass first)
2. Build Docker image
3. Push to `ghcr.io/vopsiton/riks-context-engine`
4. Deploy to production (if on `main`)

#### `issues.yml` — Issue Management

Automated issue labeling and triage.

### Running CI Locally

```bash
# Simulate the CI test matrix
for ver in 3.10 3.11 3.12; do
  echo "Testing with Python $ver"
  python$ver -m pytest --cov=src/
done
```

### Docker Build

```bash
# Build development image
docker build -t riks-context-engine:dev .

# Build production image
docker build -f Dockerfile.prod -t riks-context-engine:prod .

# Run with docker-compose
docker-compose up dev

# Run production stack
docker-compose -f docker-compose.prod.yml up -d
```

---

## Contributing Guidelines

### Branching Strategy

```
main          ← stable, always deployable
├── feature/*   ← new features
├── fix/*       ← bug fixes
└── sprint/*    ← sprint work
```

Create a feature branch:
```bash
git checkout main
git pull origin main
git checkout -b feature/my-new-feature
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Type | Example |
|------|---------|
| `feat:` | `feat: add ChromaDB vector similarity to semantic memory` |
| `fix:` | `fix: resolve context pruning edge case on tier-0 messages` |
| `docs:` | `docs: add API reference for TaskDecomposer` |
| `test:` | `test: add coverage for TierManager promotion logic` |
| `refactor:` | `refactor: extract ImportanceScorer as standalone class` |
| `chore:` | `chore: update ruff to v0.1.0` |

### Pull Request Process

1. **Fork** the repository and create a feature branch
2. **Write tests** for all new behavior
3. **Run locally:**
   ```bash
   ruff check src/
   mypy src/
   pytest
   pre-commit run --all-files
   ```
4. **Open a PR** with a clear description:
   - What does this change?
   - Why is it needed?
   - What issue does it address? (e.g., "Fixes #6")
5. **CI must pass** before merge
6. **Review** by maintainer → merge to `main`

### Reporting Issues

1. Check existing issues first
2. Include: Python version, error traceback, minimal reproduction case
3. Label with component (`memory`, `context`, `graph`, `reflection`, `cli`)

---

## Writing Tests

Tests live in `tests/`. The project uses `pytest` with `pytest-asyncio`.

### Test Structure

```python
# tests/test_memory.py
import pytest
from riks_context_engine.memory import EpisodicMemory, SemanticMemory


class TestEpisodicMemory:
    def test_add_creates_entry(self, tmp_path):
        episodic = EpisodicMemory(storage_path=str(tmp_path / "episodic.json"))
        entry = episodic.add("Test content", importance=0.8)

        assert entry.content == "Test content"
        assert entry.importance == 0.8
        assert entry.id.startswith("ep_")

    def test_query_returns_relevant(self, tmp_path):
        episodic = EpisodicMemory(storage_path=str(tmp_path / "episodic.json"))
        episodic.add("Vahit prefers Turkish", importance=0.9)
        episodic.add("Build CI pipeline", importance=0.7)

        results = episodic.query("Turkish")
        assert len(results) == 1
        assert "Vahit" in results[0].content

    def test_prune_removes_low_importance(self, tmp_path):
        episodic = EpisodicMemory(storage_path=str(tmp_path / "episodic.json"))
        for i in range(50):
            episodic.add(f"Entry {i}", importance=0.1)

        removed = episodic.prune(max_entries=10)
        assert removed > 0
        assert len(episodic) <= 10
```

### Using `tmp_path` Fixture

Always use pytest's `tmp_path` fixture for file-based storage — it creates a temporary directory per test that's automatically cleaned up:

```python
def test_persistence(self, tmp_path):
    db_path = tmp_path / "test.db"
    semantic = SemanticMemory(db_path=str(db_path))
    semantic.add("subject", "predicate", "object")

    # Reopen — should load existing data
    semantic2 = SemanticMemory(db_path=str(db_path))
    assert len(semantic2) == 1
```

### Async Tests

```python
@pytest.mark.asyncio
async def test_async_embedding():
    embedder = OllamaEmbedder()
    result = await embedder.embed_async("hello world")
    assert len(result.embedding) > 0
```

### Running Tests with Specific Markers

```bash
# Run only memory tests
pytest tests/test_memory.py -v

# Run with very verbose output
pytest tests/ -v -s

# Stop on first failure
pytest tests/ -x
```

---

## Extension Points

### Custom Embedder

Implement the `EmbedderProtocol` to use a different embedding provider (OpenAI, Gemini, etc.):

```python
from riks_context_engine.memory.embedding import set_embedder

class MyEmbedder:
    def embed(self, text: str):
        # Return EmbeddingResult or list[float]
        return my_embedding_service.encode(text)

# Replace module-level singleton
set_embedder(MyEmbedder())
```

### Custom Storage Backend

Swap file paths in constructors:

```python
from riks_context_engine.memory import EpisodicMemory

episodic = EpisuralMemory(
    storage_path="/mnt/persistent/episodic.json"
)
```

For custom serialization, subclass and override `_load` / `_save`.

### LLM Provider for Task Decomposition

```python
from riks_context_engine.tasks.decomposer import TaskDecomposer

decomposer = TaskDecomposer(llm_provider="openai")
```

The decomposer is currently keyword-based. LLM integration is planned.

### Adding a New Memory Tier

1. Create `src/riks_context_engine/memory/<new_tier>.py` with a dataclass schema
2. Define a new `MemoryType` value in `base.py`
3. Register the tier in `TierManager.auto_tier()`
4. Add tests in `tests/test_memory.py`

---

## Release Process

### Version Bumping

Version is defined in two places:
- `src/riks_context_engine/__init__.py` → `__version__`
- `pyproject.toml` → `project.version`

Update both before releasing.

### Release Checklist

```bash
# 1. Update version
#    Edit __init__.py and pyproject.toml

# 2. Run full test suite
pytest --cov=src/

# 3. Run code quality checks
ruff check src/
mypy src/
pre-commit run --all-files

# 4. Update changelog
#    Add entry in CHANGELOG.md

# 5. Commit and tag
git add -A
git commit -m "release: v0.2.0"
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin main --tags

# 6. CI/CD handles Docker build + push automatically
```

### Publishing to PyPI (future)

Once the package is ready for PyPI:

```bash
pip install build
python -m build
twine upload dist/*
```

---

_Built with 🗿 by [opsiton](https://github.com/vopsiton) for the Rik AI ecosystem._
