# Architecture Overview — Rik Context Engine

> A detailed view of the system's design, data flow, and module relationships.

**Version:** 0.2.0  
**License:** AGPL-3.0  
**Repository:** [github.com/vopsiton/riks-context-engine](https://github.com/vopsiton/riks-context-engine)

---

## Table of Contents

- [High-Level System Diagram](#high-level-system-diagram)
- [3-Tier Memory Architecture](#3-tier-memory-architecture)
- [Context Window Manager](#context-window-manager)
- [Knowledge Graph](#knowledge-graph)
- [Task Decomposer](#task-decomposer)
- [Reflection Loop](#reflection-loop)
- [Data Flow](#data-flow)
- [Storage Summary](#storage-summary)
- [Module Dependency Graph](#module-dependency-graph)
- [Extension Points](#extension-points)

---

## High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                               │
│          (chat messages, commands, goals, queries)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ContextWindowManager                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │Importance    │  │ Auto-Score   │  │ Intelligent          │   │
│  │Scorer        │→ │ & Add        │→ │ Pruning              │   │
│  │(4 dimensions)│  │              │  │ (TIER_0→3)            │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
          │                                          │
          │  record_access()                         │ promote
          ▼                                          ▼
┌──────────────────────┐              ┌──────────────────────────┐
│  EpisodicMemory      │              │  SemanticMemory           │
│  (session, JSON)     │  ──────────→ │  (long-term, SQLite +     │
│                      │  (TierManager)│   ChromaDB vectors)       │
│  Short-term facts   │              │                          │
│  Recent events      │              │  Structured facts         │
│  Ephemeral context  │              │  Subject→Predicate→Object  │
└──────────────────────┘              └──────────────────────────┘
                                              │
                                              │ consolidate
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      TierManager                                  │
│  auto_tier() every N accesses                                     │
│  - Episodic (high access_count) → Semantic                      │
│  - Semantic (low access_count) → Episodic  (if demote > 0)      │
└─────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    KnowledgeGraph                                 │
│  Entities + Relationships (SQLite)                               │
│  - BFS traversal (expand, find_path)                               │
│  - Semantic vector search (OllamaEmbedder)                       │
└─────────────────────────────────────────────────────────────────┘
          │
          │ consult_before_task()
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ReflectionAnalyzer                              │
│  Post-interaction: analyze → lessons                             │
│  Pre-task: consult unresolved lessons (critical/warning)           │
└─────────────────────────────────────────────────────────────────┘
          │
          │ success/failure feedback
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ProceduralMemory                               │
│  (skills/workflows, JSON)                                         │
│  Stores "how to" with success_rate tracking                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     LLM RESPONSE                                 │
│  (AI agent responds with full context + learned memory)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3-Tier Memory Architecture

Mirrors how humans actually remember things — short-term episodic → long-term semantic → skill-based procedural.

```
┌──────────────────────────────────────────────────────────┐
│                  EPISODIC MEMORY                          │
│  Storage:  JSON file (data/episodic.json)               │
│  Scope:    Session-level, short-term                    │
│  Access:   Frequent reads, frequent writes              │
│                                                          │
│  Schema:                                                  │
│    id | timestamp | content | importance | tags          │
│                                                          │
│  Operations:                                             │
│    add() → get() → query() → prune() → delete()          │
│                                                          │
│  Pruning: LRU — lowest importance first, when limit     │
│           exceeded (default max = 1000 entries)          │
└──────────────────────────────────────────────────────────┘

               ↑ promote (access_count > threshold)
               │                  
┌──────────────┴──────────────────────────────────────────┐
│                  SEMANTIC MEMORY                          │
│  Storage:  SQLite (data/semantic.db)                      │
│            + ChromaDB (optional vector similarity)       │
│  Scope:    Long-term, persistent across sessions        │
│  Access:   Moderate reads, moderate writes              │
│                                                          │
│  Schema (Triple Store):                                  │
│    id | subject | predicate | object | confidence       │
│                                                          │
│  Operations:                                             │
│    add() → get() → query() → recall() → delete()        │
│                                                          │
│  Embeddings: Ollama nomic-embed-text via Embedder        │
└──────────────────────────────────────────────────────────┘

               ↑ proceduralize (skill/workflow extraction)
               │
┌──────────────┴──────────────────────────────────────────┐
│                  PROCEDURAL MEMORY                         │
│  Storage:  JSON file (data/procedural.json)             │
│  Scope:    Persistent skills and workflows              │
│  Access:   Infrequent reads, occasional writes          │
│                                                          │
│  Schema:                                                  │
│    id | name | description | steps[] | success_rate     │
│                                                          │
│  Operations:                                             │
│    store() → get() → recall() → find() →                │
│    update_success_rate() → delete()                      │
└──────────────────────────────────────────────────────────┘
```

### TierManager: Automatic Promotion / Demotion

```
TierManager.auto_tier()
│
├── For each EpisodicEntry:
│   if access_count > promote_threshold:
│       Create SemanticEntry from EpisodicEntry
│       Delete EpisodicEntry
│       promoted += 1
│
└── For each SemanticEntry:
    if demote_threshold > 0 AND access_count < demote_threshold:
        Create EpisodicEntry from SemanticEntry
        Delete SemanticEntry
        demoted += 1

Returns: {"promoted": N, "demoted": N}
```

---

## Context Window Manager

Manages the conversation context with intelligent, importance-based pruning.

### Architecture

```
ContextWindowManager
│
├── __init__(max_tokens=180_000, model="mini-max")
│   │
│   └── messages: list[ContextMessage]
│       │
│       └── ContextMessage
│           ├── id, role, content, timestamp
│           ├── importance (0.0-1.0)
│           ├── tokens (estimated)
│           ├── is_grounding (user prefs / active projects)
│           ├── is_pruned
│           ├── importance_dims (4-dimension breakdown)
│           └── priority_tier (0-3)
│
├── add(role, content, importance, is_grounding, priority_tier)
│   │
│   ├── _estimate_tokens() — char-based estimate, adjusts for
│   │                         code blocks and non-Latin scripts
│   │
│   ├── _update_stats() — current_tokens, usage_percent
│   │
│   └── _prune_if_needed() ──────────────────────────────┐
│                                                        │
│   ┌─ Priority Tier Definitions ─────────────────────┐ │
│   │ TIER_0: PROTECTED  — system instructions (never)  │ │
│   │ TIER_1: HIGH       — user prefs, tool results     │ │
│   │ TIER_2: MEDIUM     — regular conversation (default)│ │
│   │ TIER_3: LOW        — old low-importance (first)   │ │
│   └───────────────────────────────────────────────────┘ │
│                                                        │
│   ┌─ Pruning Algorithm ─────────────────────────────┐ │
│   │ 1. tokens_remaining() < 0 ?                     │ │
│   │ 2. Collect candidates: not is_grounding,        │ │
│   │    not TIER_0                                    │ │
│   │ 3. Sort by pruning_score() desc                  │ │
│   │    score = -(importance * 100) - (tokens/1000)   │ │
│   │ 4. Mark lowest scores as pruned until buffer     │ │
│   │    freed (10% buffer above limit)                │ │
│   │ 5. validate_coherence()                          │ │
│   └───────────────────────────────────────────────────┘ │
│
├── auto_score_and_add(role, content, is_grounding, tier)
│   └── ImportanceScorer.score() — 4-dimension weighted average
│
├── validate_coherence()
│   └── Checks: no orphaned assistant responses,
│               no grounding lost, no excessive consecutive
│               same-role messages
│
└── get_pruning_recommendation()
    └── Returns: level (none|advisory|recommended|critical),
                tokens_to_free, tier_targets[]
```

### Importance Scoring Dimensions

| Dimension | Weight | Triggers |
|-----------|--------|---------|
| `user_mentions` | 35% | user preferences, explicit mentions |
| `new_information` | 25% | facts, results, errors, IP/ports |
| `decisions` | 25% | commitments, choices, plans, "I'll" |
| `tool_result` | 15% | tool output, function calls |

### Pruning Priority Order

```
TIER_3 (LOW) messages ────────────────────────────────── first pruned
TIER_2 (MEDIUM) messages ──────────────────────────────── pruned when needed
TIER_1 (HIGH) messages ────────────────────────────────── rarely pruned
TIER_0 (PROTECTED) messages ───────────────────────────── never pruned
Grounding messages (is_grounding=True) ────────────────── never pruned
```

---

## Knowledge Graph

Entity-relationship store with semantic vector search.

### Data Model

```
Entity
├── id: str           (e.g., "person_vahit")
├── name: str         (e.g., "Vahit")
├── entity_type: EntityType
│   ├── PERSON, PROJECT, CONCEPT, EVENT, TOOL, DOCUMENT
├── properties: dict  (e.g., {"role": "DevSecOps Lead"})
└── created_at, last_updated: datetime

Relationship
├── id: str
├── from_entity_id, to_entity_id: str
├── relationship_type: RelationshipType
│   ├── WORKS_WITH, DEPENDS_ON, USES, PARTICIPATED_IN,
│   │   KNOWS_ABOUT, RELATED_TO
├── properties: dict
├── confidence: float (0.0-1.0)
└── created_at: datetime
```

### Key Operations

```
KnowledgeGraph
│
├── add_entity(name, entity_type, properties) → Entity
│   └── Stores in SQLite, caches in memory
│
├── relate(from_entity, to_entity, relationship_type, confidence)
│   └── Creates Relationship edge
│
├── expand(entity_id, depth=N) → list[(Entity, Relationship)]
│   └── BFS traversal up to N hops from starting entity
│
├── find_path(from_entity_id, to_entity_id, max_depth=3)
│   └── BFS pathfinding — returns relationship chain or None
│
└── semantic_search(query, top_k=5, score_threshold=0.0)
    └── 1. Embed query via OllamaEmbedder
        2. Compute cosine similarity with all entity embeddings
        3. Return top-k entities sorted by score
        (Falls back to keyword search if embedder unavailable)
```

---

## Task Decomposer

Breaks complex natural-language goals into dependency-respecting task graphs.

### Decomposition Pipeline

```
"Setup auth, build Docker, run tests, deploy to production"
                    │
                    ▼
            _extract_tasks() — pattern matching
                    │
            Split by "and" / "," delimiters
                    │
                    ▼
            ┌───────┴───────┬──────────────┐
            ▼              ▼              ▼
        [Setup]        [Build]        [Deploy]
        (cat: 0)        (cat: 1)        (cat: 3)
            │              │              │
            ▼              ▼              ▼
        infer_dependencies() ← sequential within category
            │
            ▼
        TaskGraph.tasks = [Task_1, Task_2, Task_3]
        Task_2.dependencies = [Task_1.id]
        Task_3.dependencies = [Task_2.id]
                    │
                    ▼
        validate_graph() — cycle detection (DFS)
                    │
                    ▼
        plan_execution() — topological batching
                    │
                    ▼
        [[Task_1], [Task_2], [Task_3]]  (sequential batches)
```

### Task Lifecycle

```
PENDING ──[can_execute]──→ RUNNING ──[success]──→ DONE
  │                              │
  │                              └──[failure]──→ FAILED
  │
  └──[dependency unmet]──────────→ SKIPPED
```

---

## Reflection Loop

Self-improvement system that learns from interactions.

```
Interaction ends
      │
      ▼
ReflectionAnalyzer.analyze(interaction_id, conversation)
      │
      ▼
┌────────────────────────────────────────────────────────┐
│  Pattern Matching on each message:                     │
│                                                        │
│  went_well?  ← "success", "works", "solved", "great"  │
│  went_wrong? ← "error", "fail", "wrong", "bug"        │
│  missing?    ← "didn't know", "missing", "unclear"    │
└────────────────────────────────────────────────────────┘
      │
      ▼
detect_category() — regex patterns across 6 categories:
  tool-use | context-management | task-planning |
  communication | security | general
      │
      ▼
extract_severity() — info | warning | critical
  (critical: "security", "breach", "data loss")
      │
      ▼
Merge with existing lessons
  (same category + severity → increment occurrence_count)
      │
      ▼
ReflectionReport:
  - went_well: list[str]
  - went_wrong: list[str]
  - missing_info: list[str]
  - lessons: list[Lesson]
      │
      ▼
Pre-task consultation:
consult_before_task(task_description)
  → relevant unresolved lessons (critical/warning only)
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              ContextWindowManager.add()                          │
│  1. _estimate_tokens()                                          │
│  2. auto_score_and_add() → ImportanceScorer                     │
│  3. _prune_if_needed() — may mark messages is_pruned=True      │
│  4. _update_stats()                                            │
└─────────────────────────────────────────────────────────────────┘
          │                                          │
          │ episodic.add()                          │ semantic.add()
          ▼                                          ▼
┌──────────────────────┐              ┌──────────────────────────┐
│  EpisodicMemory       │              │  SemanticMemory           │
│  write to JSON file   │              │  write to SQLite          │
└──────────────────────┘              └──────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    TierManager.auto_tier()                        │
│  Monitors access_count across episodic / semantic                │
│  Promotes high-access episodic → semantic                        │
│  Demotes low-access semantic → episodic (if threshold > 0)      │
└──────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    KnowledgeGraph                                  │
│  add_entity() / relate() — persist to SQLite                     │
│  semantic_search() — embed query → cosine similarity            │
└──────────────────────────────────────────────────────────────────┘
          │                                          │
          ▼                                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                  ReflectionAnalyzer                               │
│  analyze() after interaction                                    │
│  consult_before_task() before new interaction                   │
│  record_success() / record_failure() — updates lesson DB        │
└──────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                 ProceduralMemory                                  │
│  store() skill with steps + success_rate                        │
│  find() — recall "how to" for similar goals                     │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     LLM RESPONSE                                 │
│  (context window includes active + grounded messages,           │
│   knowledge graph provides entity context,                      │
│   reflection provides past lessons)                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Storage Summary

| Component | File | Format | Persists? | Concurrency |
|-----------|------|--------|-----------|------------|
| Episodic Memory | `data/episodic.json` | JSON | Yes | Single-writer |
| Semantic Memory | `data/semantic.db` | SQLite | Yes | Thread-safe (shared conn) |
| Procedural Memory | `data/procedural.json` | JSON | Yes | Single-writer |
| Knowledge Graph | `data/knowledge_graph.db` | SQLite | Yes | Thread-safe |
| Context Window | In-memory | Python objects | **No** (lost on restart) | Single-thread |
| Ollama Embeddings | ChromaDB (optional) | Vector store | Yes | Server-managed |
| CLI Config | `.env` | Env file | Yes | N/A |

---

## Module Dependency Graph

```
__init__.py (version only)
│
└── context/manager.py
    ├── ContextWindowManager
    ├── ContextMessage
    ├── ContextStats
    ├── ImportanceScorer
    └── TIER_* constants

memory/
├── base.py          ← no dependencies (foundation)
├── episodic.py      ← no dependencies
├── semantic.py      ← no dependencies (SQLite direct)
├── procedural.py   ← no dependencies
├── embedding.py    ← httpx (external HTTP)
└── tier_manager.py ← episodic.py, semantic.py, procedural.py, base.py

graph/knowledge_graph.py
└── memory/embedding.py (OllamaEmbedder)

tasks/decomposer.py ← no external dependencies

reflection/analyzer.py
└── (optional) memory/semantic.py

cli/main.py ← no internal dependencies (standalone entry point)
```

---

## Extension Points

### 1. Custom Embedder

```python
# Any object with an embed(text: str) → list[float] method
from riks_context_engine.memory.embedding import set_embedder

class OpenAIEmbedder:
    def embed(self, text: str):
        return openai.embeddings.create(input=text, model="text-embedding-3").data[0].embedding

set_embedder(OpenAIEmbedder())
```

### 2. Custom Storage Paths

```python
EpisodicMemory(storage_path="/custom/path/episodic.json")
SemanticMemory(db_path="/custom/path/semantic.db")
ProceduralMemory(storage_path="/custom/path/procedural.json")
KnowledgeGraph(db_path="/custom/path/knowledge_graph.db")
```

### 3. Custom Tier Thresholds

```python
from riks_context_engine.memory.tier_manager import TierManager, TierConfig

config = TierConfig(
    promote_threshold=10,         # More accesses before promotion
    demote_threshold=0,         # Never demote (keep long-term)
    max_episodic=500,            # Smaller episodic cache
    check_interval_accesses=5,   # Check more frequently
)
tier_manager = TierManager(episodic, semantic, procedural, config)
```

### 4. Custom LLM Provider for Task Decomposition

```python
decomposer = TaskDecomposer(llm_provider="openai")
# Currently keyword-based; LLM integration planned
```

### 5. New Memory Tier

1. Add `MemoryType` value in `memory/base.py`
2. Create `memory/<new_tier>.py` with schema and storage
3. Register in `TierManager.auto_tier()`
4. Export from `memory/__init__.py`

---

_Built with 🗿 by [opsiton](https://github.com/vopsiton) for the Rik AI ecosystem._
