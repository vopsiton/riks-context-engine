# Rik Context Engine 🗿

> **AI Context & Memory Engine for agents that actually remember.**

[![AGPL License](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![Build Status](https://img.shields.io/badge/Status-Alpha-orange.svg)](#)

**Rik Context Engine** gives AI agents a persistent, hierarchical memory — so they stop forgetting and start learning.

---

## The Problem

Every AI session starts from scratch. Chat with an assistant today, and tomorrow it's a complete stranger who has no idea who you are, what you were working on, or what you hate.

The industry keeps building bigger context windows. But bigger windows don't solve the *memory problem* — they just delay it.

**Context windows ≠ Memory.**

- 128K context window = you can fit a novel, not a relationship
- Long conversations get truncated, losing the most important context
- No differentiation between "what happened" and "what matters"
- Zero learning across sessions

---

## The Solution: 3-Tier Human Memory Architecture

Rik Context Engine mirrors how humans actually remember things:

```
┌─────────────────────────────────────────────────────────┐
│                  Episodic Memory                         │
│         Session-level, short-term, high-fidelity         │
│     "What happened in this conversation last week?"      │
│                  (JSON file storage)                      │
└─────────────────────────────────────────────────────────┘
                          ↓ consolidate
┌─────────────────────────────────────────────────────────┐
│                  Semantic Memory                         │
│         Long-term structured knowledge (SQLite)          │
│     "What do I know about this user/project?"             │
│             + ChromaDB vector search                       │
└─────────────────────────────────────────────────────────┘
                          ↓ proceduralize
┌─────────────────────────────────────────────────────────┐
│                 Procedural Memory                         │
│           Skills, workflows, how-to knowledge             │
│        "How do I deploy to the production server?"        │
│                   (JSON file storage)                     │
└─────────────────────────────────────────────────────────┘
```

### Core Components

| Component | What it does |
|-----------|-------------|
| **Context Window Manager** | Intelligent pruning — scores message importance, preserves what matters, maintains coherence |
| **3-Tier Memory** | Episodic (session) + Semantic (long-term facts) + Procedural (skills/workflows) |
| **Knowledge Graph** | Entity relationships with semantic vector search |
| **Task Decomposer** | Breaks complex goals into dependency-respecting task graphs |
| **Reflection Analyzer** | Self-improvement loop — learns from mistakes, tracks patterns |

---

## Features

### 🧠 Intelligent Context Window Management
- **Importance scoring** — Automatically scores messages based on user mentions, decisions, tool results, and new information
- **Smart pruning** — Removes low-importance content before high-importance, never loses grounding context
- **Coherence validation** — Ensures pruned context remains logically coherent
- **Priority tiers** — TIER_0 (protected system instructions) → TIER_3 (low-priority old messages)

### 📦 3-Tier Memory System
- **Episodic**: Session snapshots, conversation highlights, ephemeral facts
- **Semantic**: Structured knowledge (subject→predicate→object), SQLite-backed with ChromaDB embeddings
- **Procedural**: Captured skills, workflows with success rates, step-by-step instructions

### 🔗 Knowledge Graph
- Entity + relationship model with types (PERSON, PROJECT, CONCEPT, TOOL, etc.)
- BFS pathfinding between entities
- Semantic vector search via Ollama embeddings
- Relationship traversal with configurable depth

### 📋 Task Decomposition
- Goal → executable task graph with dependency resolution
- Parallel execution groups
- Success criteria and rollback steps per task
- Cycle detection and validation

### 🔄 Self-Reflection Loop
- Post-interaction analysis identifying what went well/wrong
- Category-tagged lessons (tool-use, context-management, task-planning, security)
- Severity tracking (info → warning → critical)
- Consult-before-task: checks past lessons before new work

---

## Quick Start

### Python (Local)

```bash
# Clone
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine

# Virtual environment
python -m venv .venv && source .venv/bin/activate

# Install
pip install -e ".[dev]"

# Try it
python -c "
from riks_context_engine import *
from riks_context_engine.memory import EpisodicMemory, SemanticMemory, ProceduralMemory
from riks_context_engine.context import ContextWindowManager

# Add a memory
mem = EpisodicMemory()
mem.add('Vahit prefers Turkish in technical discussions', importance=0.9)

# Use context manager
ctx = ContextWindowManager(max_tokens=50_000)
ctx.add('user', 'Deploy to production', importance=0.8, is_grounding=True)
print(ctx.get_summary())
"
```

### Docker

```bash
# Build
docker build -t riks-context-engine:dev .

# Run with docker-compose
docker-compose up dev

# Inside container
docker-compose exec dev python -c "from riks_context_engine import *; print('OK')"
```

---

## Architecture

```
src/riks_context_engine/
├── __init__.py              # Package entry point
├── memory/
│   ├── base.py              # MemoryEntry schema (unified 3-tier format)
│   ├── episodic.py          # EpisodicMemory — session-level JSON store
│   ├── semantic.py          # SemanticMemory — SQLite + ChromaDB
│   ├── procedural.py        # ProceduralMemory — skills & workflows
│   └── embedding.py         # Ollama embedder integration
├── context/
│   └── manager.py           # ContextWindowManager — intelligent pruning
├── tasks/
│   └── decomposer.py        # TaskDecomposer — goal → task graph
├── graph/
│   └── knowledge_graph.py   # KnowledgeGraph — entities + relationships
├── reflection/
│   └── analyzer.py          # ReflectionAnalyzer — self-improvement
└── cli/
    └── main.py              # CLI entry point (`riks` command)
```

---

## Storage Backends

| Tier | Storage | Why |
|------|---------|-----|
| Episodic | JSON file (`data/episodic.json`) | Fast writes, simple, session-scoped |
| Semantic | SQLite (`data/semantic.db`) + ChromaDB | Relational queries + vector search |
| Procedural | JSON file (`data/procedural.json`) | Human-readable, easy to edit |
| Knowledge Graph | SQLite (`data/knowledge_graph.db`) | Graph queries with foreign keys |
| Context Window | In-memory | Transient, not persisted |

---

## Configuration

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server for embeddings |
| `OLLAMA_MODEL` | `gemma4-31b-q4` | Default LLM for task decomposition |
| `CHROMA_HOST` | `localhost` | ChromaDB server for semantic search |
| `DATA_DIR` | `/app/data` | Data storage directory |

---

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/

# Type check
mypy src/

# Pre-commit hooks
pre-commit run --all-files
```

---

## License

[AGPL-3.0](./LICENSE) — share the source if you build on it.

---

*Built with 🗿 by [opsiton](https://github.com/vopsiton) for the Rik AI ecosystem.*
