# User Guide — Rik Context Engine

> AI Context & Memory Engine for agents that actually remember.

**Version:** 0.2.0 | **Python:** 3.10+ | **License:** AGPL-3.0

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Core Concepts](#core-concepts)
- [API Overview](#api-overview)
- [Examples](#examples)
- [Storage Backends](#storage-backends)
- [CLI Reference](#cli-reference)

---

## Installation

### Option 1 — pip (Recommended)

```bash
# Clone the repository
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows

# Install with all dependencies
pip install -e ".[dev]"

# Verify
python -c "from riks_context_engine import *; print('OK')"
```

### Option 2 — pip install from PyPI (when published)

```bash
pip install riks-context-engine
```

### Option 3 — Docker

```bash
# Build the image
docker build -t riks-context-engine:dev .

# Run with docker-compose (development)
docker-compose up dev

# Inside the container
docker-compose exec dev python -c "from riks_context_engine import *; print('OK')"
```

For production with persistent volumes:
```bash
docker-compose -f docker-compose.prod.yml up -d
```

### Option 4 — With OpenAI/Anthropic providers

```bash
# OpenAI models (GPT-4, etc.)
pip install -e ".[openai]"

# Anthropic models (Claude, etc.)
pip install -e ".[anthropic]"
```

---

## Quick Start

### 1. Import and Initialize

```python
from riks_context_engine.memory import (
    EpisodicMemory,
    SemanticMemory,
    ProceduralMemory,
)
from riks_context_engine.context import ContextWindowManager
from riks_context_engine.graph import KnowledgeGraph
from riks_context_engine.reflection import ReflectionAnalyzer

# Initialize stores
episodic = EpisodicMemory()
semantic = SemanticMemory()
procedural = ProceduralMemory()
graph = KnowledgeGraph()
reflection = ReflectionAnalyzer()

# Initialize context window manager
ctx = ContextWindowManager(max_tokens=50_000)
```

### 2. Add Memories

```python
# Episodic — session-level observations
ep = episodic.add(
    content="Vahit prefers Turkish in technical discussions",
    importance=0.9,
    tags=["preference", "language"],
)
print(f"Created: {ep.id}")

# Semantic — structured facts
sm = semantic.add(
    subject="opsiton",
    predicate="is_a",
    object="DevSecOps company",
    confidence=0.95,
)
print(f"Created: {sm.id}")

# Procedural — skills / workflows
proc = procedural.store(
    name="deploy-production",
    description="Deploy application to production server",
    steps=[
        "1. Run tests: pytest",
        "2. Build image: docker build",
        "3. Push to registry",
        "4. Deploy with docker-compose",
    ],
    tags=["deployment", "docker"],
)
print(f"Stored: {proc.name}")
```

### 3. Manage Context Window

```python
# Add messages with importance scoring
ctx.add("user", "Deploy to production", importance=0.8, is_grounding=True)
ctx.add("assistant", "I'll deploy the v2.1.0 release now.", importance=0.7)
ctx.add("tool", "Build complete: sha256 abc123...", importance=0.9, role="tool")

# Check window status
print(ctx.get_summary())
# {
#   'max_tokens': 50000,
#   'current_tokens': 42,
#   'active_messages': 3,
#   'tokens_remaining': 49958,
#   'usage_percent': 0.08,
#   'needs_pruning': False,
# }

# Auto-score and add (importance inferred from content)
msg = ctx.auto_score_and_add(
    role="user",
    content="Remember: never use rm -rf / in production",
    is_grounding=True,
)
print(f"Auto-scored importance: {msg.importance}")
# Auto-scored importance: 0.85
```

### 4. Query Memories

```python
# Episodic — keyword search
results = episodic.query("Turkish", limit=5)
for r in results:
    print(f"  [{r.importance}] {r.content}")

# Semantic — triple-store query
results = semantic.query(subject="opsiton")
for r in results:
    print(f"  {r.subject} {r.predicate} {r.object}")

# Procedural — find skill
procs = procedural.find("deploy")
for p in procs:
    print(f"  {p.name} (success_rate={p.success_rate})")
```

### 5. Knowledge Graph

```python
from riks_context_engine.graph import KnowledgeGraph, EntityType, RelationshipType

graph = KnowledgeGraph()

# Add entities
vahit = graph.add_entity("Vahit", EntityType.PERSON, {"role": "DevSecOps Lead"})
opsiton = graph.add_entity("opsiton", EntityType.PROJECT, {"focus": "AI infrastructure"})

# Relate them
graph.relate(vahit, opsiton, RelationshipType.WORKS_ON)

# Expand from an entity
connections = graph.expand(vahit.id, depth=1)
for entity, rel in connections:
    print(f"  {entity.name} ({entity.entity_type.value}) — via {rel.relationship_type.value}")

# Semantic search
results = graph.semantic_search("AI infrastructure projects", top_k=5)
for entity, score in results:
    print(f"  {entity.name}: {score:.3f}")
```

---

## Configuration

Copy the example env file:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server for embeddings |
| `OLLAMA_MODEL` | `gemma4-31b-q4` | Default LLM for task decomposition |
| `CHROMA_HOST` | `localhost` | ChromaDB server for semantic search |
| `DATA_DIR` | `/app/data` | Data storage directory |

### Python Configuration

```python
from riks_context_engine.memory.embedding import OllamaEmbedder, set_embedder

# Custom embedder
embedder = OllamaEmbedder(
    base_url="http://my-ollama:11434",
    model="nomic-embed-text",
    timeout=60.0,
)
set_embedder(embedder)
```

### Context Window Configuration

```python
from riks_context_engine.context.manager import ContextWindowManager

ctx = ContextWindowManager(
    max_tokens=100_000,  # Default: 180,000
    model="gpt-4",       # For token estimation
)
```

### Tier Manager Configuration

```python
from riks_context_engine.memory.tier_manager import TierManager, TierConfig, EpisodicMemory, SemanticMemory, ProceduralMemory

config = TierConfig(
    promote_threshold=5,          # Accesses before promoting episodic → semantic
    demote_threshold=0,            # 0 = never demote
    max_episodic=1000,             # Max episodic entries before pruning
    check_interval_accesses=10,   # Run auto_tier every N accesses
)

tier_manager = TierManager(
    episodic=episodic,
    semantic=semantic,
    procedural=procedural,
    config=config,
)
```

---

## Core Concepts

### 3-Tier Memory Architecture

Rik Context Engine mirrors how humans remember things:

```
┌─────────────────────────────────────────────────────────┐
│                  Episodic Memory                         │
│         Session-level, short-term, high-fidelity         │
│     "What happened in this conversation?"                │
│                  (JSON file storage)                      │
└─────────────────────────────────────────────────────────┘
                          ↓ consolidate
┌─────────────────────────────────────────────────────────┐
│                  Semantic Memory                         │
│         Long-term structured knowledge (SQLite)          │
│     "What do I know about this user?"                   │
│             + ChromaDB vector search                     │
└─────────────────────────────────────────────────────────┘
                          ↓ proceduralize
┌─────────────────────────────────────────────────────────┐
│                 Procedural Memory                         │
│           Skills, workflows, how-to knowledge             │
│        "How do I deploy to production?"                  │
│                   (JSON file storage)                     │
└─────────────────────────────────────────────────────────┘
```

### Context Window Manager

The context window manager automatically:
1. **Scores importance** — 4 dimensions: user mentions, decisions, new info, tool results
2. **Prunes intelligently** — lowest-importance messages first, protected tiers never pruned
3. **Validates coherence** — ensures pruned context remains logically coherent

### Priority Tiers

| Tier | Name | What it contains | Pruning |
|------|------|-------------------|--------|
| 0 | PROTECTED | System instructions, critical config | Never |
| 1 | HIGH | User preferences, tool results, decisions | Rarely |
| 2 | MEDIUM | Regular conversation | Yes |
| 3 | LOW | Older, low-importance messages | First |

---

## API Overview

### EpisodicMemory

```python
episodic = EpisodicMemory(storage_path="data/episodic.json")

entry = episodic.add(content, importance=0.5, tags=None, embedding=None)
entry = episodic.get(entry_id)
results = episodic.query(query, limit=10)
count = episodic.prune(max_entries=1000)
deleted = episodic.delete(entry_id)
length = len(episodic)
```

### SemanticMemory

```python
semantic = SemanticMemory(db_path="data/semantic.db", embedder=None)

entry = semantic.add(subject, predicate, object, confidence=1.0, embedding=None)
entry = semantic.get(entry_id)
results = semantic.query(subject=None, predicate=None)
results = semantic.recall(query)
deleted = semantic.delete(entry_id)
length = len(semantic)
```

### ProceduralMemory

```python
procedural = ProceduralMemory(storage_path="data/procedural.json")

proc = procedural.store(name, description, steps, tags=None)
proc = procedural.get(proc_id)
proc = procedural.recall(name)          # Exact match
procs = procedural.find(query)           # Fuzzy search
updated = procedural.update_success_rate(proc_id, success=True)
deleted = procedural.delete(proc_id)
length = len(procedural)
```

### ContextWindowManager

```python
ctx = ContextWindowManager(max_tokens=50_000, model="mini-max")

msg = ctx.add(role, content, importance=0.5, is_grounding=False, priority_tier=2)
msg = ctx.auto_score_and_add(role, content, is_grounding=False, priority_tier=2)
messages = ctx.get_messages(include_pruned=False)
active_tokens = ctx.get_active_tokens()
remaining = ctx.tokens_remaining()
needs_prune = ctx.needs_pruning()
valid, score = ctx.validate_coherence()
summary = ctx.get_summary()
recommendation = ctx.get_pruning_recommendation()
ctx.reset()
```

### KnowledgeGraph

```python
graph = KnowledgeGraph(db_path="data/knowledge_graph.db")

entity = graph.add_entity(name, entity_type, properties=None)
rel = graph.relate(from_entity, to_entity, relationship_type, confidence=1.0)
results = graph.query(entity_name=None, relationship_type=None)
connections = graph.expand(entity_id, depth=1)
path = graph.find_path(from_entity_id, to_entity_id, max_depth=3)
results = graph.semantic_search(query, top_k=5, score_threshold=0.0)
```

### TaskDecomposer

```python
from riks_context_engine.tasks.decomposer import TaskDecomposer

decomposer = TaskDecomposer(llm_provider="ollama")
graph = decomposer.decompose("Setup auth, build Docker, deploy to production")
plan = decomposer.plan_execution(graph)
valid, error = decomposer.validate_graph(graph)
graph = decomposer.execute(graph)
```

### ReflectionAnalyzer

```python
reflection = ReflectionAnalyzer(semantic_memory=None)

report = reflection.analyze(interaction_id, conversation)
lessons = reflection.consult_before_task(task_description)
reflection.record_success(task_id, details)
reflection.record_failure(task_id, error, root_cause=None)
mistakes = reflection.track_mistake_frequency()
active = reflection.get_active_lessons()
resolved = reflection.resolve_lesson(lesson_id)
```

---

## Examples

### Example 1 — AI Conversation with Memory

```python
from riks_context_engine.context.manager import ContextWindowManager
from riks_context_engine.memory import EpisodicMemory, SemanticMemory

episodic = EpisodicMemory()
semantic = SemanticMemory()

ctx = ContextWindowManager(max_tokens=50_000)

# User's first message
ctx.add("user", "I'm Vahit, I work on AI infrastructure at opsiton", importance=0.9, is_grounding=True)

# Store as semantic fact
semantic.add("Vahit", "works_at", "opsiton", confidence=0.95)
semantic.add("opsiton", "focuses_on", "AI infrastructure", confidence=0.9)

# Assistant responds
ctx.add("assistant", "Nice to meet you Vahit! I'll remember your context.", importance=0.7)

# User asks a question
ctx.add("user", "How do I deploy to production?", importance=0.8)

# Later, retrieve the grounding context
for msg in ctx.get_messages():
    if msg.is_grounding:
        print(f"Grounding: {msg.content}")
```

### Example 2 — Task Decomposition

```python
from riks_context_engine.tasks.decomposer import TaskDecomposer

decomposer = TaskDecomposer()
graph = decomposer.decompose(
    "Setup authentication, build Docker image, run tests, deploy to production"
)

print(f"Goal: {graph.goal}")
for task in graph.tasks:
    print(f"  [{task.id}] {task.name}")
    print(f"       deps: {task.dependencies}")
    print(f"       success: {task.success_criteria}")

# Validate for cycles
valid, error = decomposer.validate_graph(graph)
if not valid:
    print(f"INVALID: {error}")

# Plan execution
plan = decomposer.plan_execution(graph)
for i, batch in enumerate(plan):
    print(f"Step {i+1}: {[t.name for t in batch]}")
```

### Example 3 — Reflection Loop

```python
from riks_context_engine.reflection import ReflectionAnalyzer

reflection = ReflectionAnalyzer()

conversation = [
    {"role": "user", "content": "Deploy the new version"},
    {"role": "assistant", "content": "Starting deployment..."},
    {"role": "tool", "content": "ERROR: connection refused on port 22"},
    {"role": "assistant", "content": "Retrying with SSH key auth..."},
    {"role": "tool", "content": "Deployment successful"},
]

report = reflection.analyze("session-42", conversation)

print(f"Went well: {report.went_went_well}")
print(f"Went wrong: {report.went_wrong}")
print(f"Lessons: {len(report.lessons)}")
for lesson in report.lessons:
    print(f"  [{lesson.severity}] {lesson.category}: {lesson.lesson_text}")

# Before next deployment task, consult past lessons
prior_lessons = reflection.consult_before_task("deploy new version")
if prior_lessons:
    print("Heads up:")
    for lesson in prior_lessons:
        print(f"  - {lesson.lesson_text}")
```

### Example 4 — Knowledge Graph with Semantic Search

```python
from riks_context_engine.graph import KnowledgeGraph, EntityType, RelationshipType

graph = KnowledgeGraph()

# Build a small knowledge graph
vahit = graph.add_entity("Vahit", EntityType.PERSON, {"role": "DevSecOps Lead"})
rik = graph.add_entity("Rik", EntityType.TOOL, {"type": "AI assistant"})
ai = graph.add_entity("AI infrastructure", EntityType.CONCEPT, {})
opsiton = graph.add_entity("opsiton", EntityType.PROJECT, {})

graph.relate(vahit, opsiton, RelationshipType.WORKS_ON)
graph.relate(rik, ai, RelationshipType.USES)
graph.relate(vahit, rik, RelationshipType.WORKS_WITH)

# Find path between two entities
path = graph.find_path(vahit.id, ai.id, max_depth=3)
if path:
    print("Path found:")
    for rel in path:
        print(f"  {rel.from_entity_id} --{rel.relationship_type.value}--> {rel.to_entity_id}")

# Semantic search
results = graph.semantic_search("DevSecOps AI assistant", top_k=3)
for entity, score in results:
    print(f"  {entity.name} ({entity.entity_type.value}): {score:.3f}")
```

---

## Storage Backends

| Tier | Storage | Format | Persists Across Sessions |
|------|---------|--------|--------------------------|
| Episodic | `data/episodic.json` | JSON | Yes |
| Semantic | `data/semantic.db` | SQLite | Yes |
| Procedural | `data/procedural.json` | JSON | Yes |
| Knowledge Graph | `data/knowledge_graph.db` | SQLite | Yes |
| Context Window | In-memory | Python objects | No |
| Embeddings | ChromaDB (optional) | Vector store | Yes |

### Custom Storage Paths

```python
episodic = EpisodicMemory(storage_path="/custom/path/episodic.json")
semantic = SemanticMemory(db_path="/custom/path/semantic.db")
procedural = ProceduralMemory(storage_path="/custom/path/procedural.json")
graph = KnowledgeGraph(db_path="/custom/path/knowledge_graph.db")
```

---

## CLI Reference

```bash
# Show version
riks --version

# Memory operations
riks memory add --type episodic "Remember Vahit prefers Turkish"
riks memory query --type semantic "opsiton"
riks memory stats --type procedural

# Context window operations
riks context stats
riks context prune
riks context clear

# Task decomposition
riks task "Setup auth, build Docker, deploy to production" --execute

# Reflection
riks reflect --session abc123
```

---

## Troubleshooting

### Ollama connection error

```
Cannot connect to Ollama at http://localhost:11434. Is Ollama running?
```

**Fix:** Start Ollama or set a different host:
```python
from riks_context_engine.memory.embedding import OllamaEmbedder, set_embedder
set_embedder(OllamaEmbedder(base_url="http://your-ollama:11434"))
```

### ChromaDB not available

ChromaDB is optional. The system falls back to SQLite keyword search when ChromaDB is unavailable. Install ChromaDB if you need vector similarity:

```bash
pip install chromadb>=0.4.0
```

### Token estimation is imprecise

`ContextWindowManager` uses character-based estimation by default (~4 chars/token). Install `tiktoken` for accurate token counting:

```bash
pip install tiktoken
```

---

_Built with 🗿 by [opsiton](https://github.com/vopsiton) for the Rik AI ecosystem._
