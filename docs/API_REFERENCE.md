# API Reference — Rik Context Engine

> Complete API documentation for `riks-context-engine` v0.2.0.

**Note:** No authentication is required for local in-process usage. All modules are used directly via Python imports.

---

## Table of Contents

- [Memory System](#memory-system)
  - [MemoryEntry / MemoryType](#memoryentry--memorytype)
  - [EpisodicMemory](#episodicmemory)
  - [SemanticMemory](#semanticmemory)
  - [ProceduralMemory](#proceduralmemory)
  - [OllamaEmbedder](#ollamaembedder)
  - [TierManager](#tiermanager)
- [Context Window](#context-window)
  - [ImportanceScorer](#importancescorer)
  - [ContextMessage](#contextmessage)
  - [ContextWindowManager](#contextwindowmanager)
- [Knowledge Graph](#knowledge-graph)
  - [Entity / EntityType](#entity--entitytype)
  - [Relationship / RelationshipType](#relationship--relationshiptype)
  - [KnowledgeGraph](#knowledgegraph)
- [Task Decomposition](#task-decomposition)
  - [Task / TaskStatus](#task--taskstatus)
  - [TaskGraph](#taskgraph)
  - [TaskDecomposer](#taskdecomposer)
- [Reflection](#reflection)
  - [Lesson / Severity](#lesson--severity)
  - [ReflectionReport](#reflectionreport)
  - [ReflectionAnalyzer](#reflectionanalyzer)
- [CLI](#cli)

---

## Memory System

### MemoryEntry / MemoryType

**File:** `src/riks_context_engine/memory/base.py`

```python
from riks_context_engine.memory.base import MemoryEntry, MemoryType
```

#### `MemoryType`

Enum discriminator for the three memory tiers.

| Value | Description |
|-------|-------------|
| `MemoryType.EPISODIC` | Session-level, short-term observations |
| `MemoryType.SEMANTIC` | Long-term structured knowledge |
| `MemoryType.PROCEDURAL` | Skills and workflows |

#### `MemoryEntry`

Unified schema for all memory entries.

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique identifier, prefixed by tier (e.g. `ep_123`) |
| `type` | `MemoryType` | Which tier this entry belongs to |
| `content` | `str` | Human-readable fact or observation |
| `timestamp` | `datetime` | UTC creation timestamp |
| `importance` | `float` | Significance score in [0.0, 1.0] |
| `embedding` | `list[float] \| None` | Vector representation for semantic search |
| `access_count` | `int` | Number of times this entry has been retrieved |
| `last_accessed` | `datetime \| None` | UTC timestamp of most recent retrieval |
| `metadata` | `dict[str, Any]` | Tier-specific extra fields |

**Methods:**

```python
entry.record_access() -> None
# Increments access_count and updates last_accessed.

entry.to_dict() -> dict[str, Any]
# Serialize to JSON-compatible dict.

entry = MemoryEntry.from_dict(data: dict[str, Any]) -> MemoryEntry
# Reconstruct from dict.
```

---

### EpisodicMemory

**File:** `src/riks_context_engine/memory/episodic.py`

```python
from riks_context_engine.memory import EpisodicMemory
# or
from riks_context_engine.memory.episodic import EpisodicMemory
```

```python
episodic = EpisodicMemory(storage_path: str | None = None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `storage_path` | `str \| None` | `"data/episodic.json"` | Path to JSON storage file |

**Methods:**

```python
entry = episodic.add(
    content: str,
    importance: float = 0.5,
    tags: list[str] | None = None,
    embedding: list[float] | None = None,
) -> EpisodicEntry
```

```python
entry = episodic.get(entry_id: str) -> EpisodicEntry | None
# Returns entry and increments access_count.
```

```python
results = episodic.query(query: str, limit: int = 10) -> list[EpisodicEntry]
# Keyword + tag search, sorted by importance desc then timestamp desc.
```

```python
removed = episodic.prune(max_entries: int = 1000) -> int
# Removes lowest-importance entries when limit exceeded. Returns count removed.
```

```python
deleted = episodic.delete(entry_id: str) -> bool
```

```python
length = len(episodic) -> int
```

**EpisodicEntry attributes:**

| Attribute | Type |
|-----------|------|
| `id` | `str` |
| `timestamp` | `datetime` |
| `content` | `str` |
| `importance` | `float` (0.0–1.0) |
| `embedding` | `list[float] \| None` |
| `tags` | `list[str] \| None` |
| `access_count` | `int` |
| `last_accessed` | `datetime \| None` |

---

### SemanticMemory

**File:** `src/riks_context_engine/memory/semantic.py`

```python
from riks_context_engine.memory import SemanticMemory
# or
from riks_context_engine.memory.semantic import SemanticMemory
```

```python
semantic = SemanticMemory(db_path: str | None = None, embedder: Any = None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `"data/semantic.db"` | Path to SQLite database |
| `embedder` | `Any` | `None` | Ollama embedder instance |

**Methods:**

```python
entry = semantic.add(
    subject: str,
    predicate: str,
    object: str | None = None,
    confidence: float = 1.0,
    embedding: list[float] | None = None,
) -> SemanticEntry
```

```python
entry = semantic.get(entry_id: str) -> SemanticEntry | None
# Returns entry and increments access_count.
```

```python
results = semantic.query(
    subject: str | None = None,
    predicate: str | None = None,
) -> list[SemanticEntry]
# Triple-store search. Partial match (LIKE) on subject/predicate.
```

```python
results = semantic.recall(query: str) -> list[SemanticEntry]
# Keyword search across subject, predicate, and object.
```

```python
deleted = semantic.delete(entry_id: str) -> bool
```

```python
length = len(semantic) -> int
```

**SemanticEntry attributes:**

| Attribute | Type |
|-----------|------|
| `id` | `str` |
| `subject` | `str` |
| `predicate` | `str` |
| `object` | `str \| None` |
| `confidence` | `float` (0.0–1.0) |
| `created_at` | `datetime` |
| `last_accessed` | `datetime` |
| `access_count` | `int` |
| `embedding` | `list[float] \| None` |

---

### ProceduralMemory

**File:** `src/riks_context_engine/memory/procedural.py`

```python
from riks_context_engine.memory import ProceduralMemory
# or
from riks_context_engine.memory.procedural import ProceduralMemory
```

```python
procedural = ProceduralMemory(storage_path: str | None = None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `storage_path` | `str \| None` | `"data/procedural.json"` | Path to JSON storage file |

**Methods:**

```python
proc = procedural.store(
    name: str,
    description: str,
    steps: list[str],
    tags: list[str] | None = None,
) -> Procedure
```

```python
proc = procedural.get(proc_id: str) -> Procedure | None
# Updates use_count and last_used.
```

```python
proc = procedural.recall(name: str) -> Procedure | None
# Exact name match (case-insensitive).
```

```python
procs = procedural.find(query: str) -> list[Procedure]
# Fuzzy search on name, description, tags. Sorted by use_count desc then success_rate desc.
```

```python
updated = procedural.update_success_rate(proc_id: str, success: bool) -> bool
# Running average update of success_rate.
```

```python
deleted = procedural.delete(proc_id: str) -> bool
```

```python
length = len(procedural) -> int
```

**Procedure attributes:**

| Attribute | Type |
|-----------|------|
| `id` | `str` |
| `name` | `str` |
| `description` | `str` |
| `steps` | `list[str]` |
| `created_at` | `datetime` |
| `last_used` | `datetime` |
| `use_count` | `int` |
| `success_rate` | `float` (0.0–1.0) |
| `tags` | `list[str]` |

---

### OllamaEmbedder

**File:** `src/riks_context_engine/memory/embedding.py`

```python
from riks_context_engine.memory.embedding import (
    OllamaEmbedder,
    EmbeddingResult,
    OllamaEmbeddingError,
    get_embedder,
    set_embedder,
)
```

```python
embedder = OllamaEmbedder(
    base_url: str | None = None,
    model: str = "nomic-embed-text",
    timeout: float = 30.0,
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | `str \| None` | `OLLAMA_BASE_URL` env or `http://localhost:11434` | Ollama server URL |
| `model` | `str` | `"nomic-embed-text"` | Embedding model name |
| `timeout` | `float` | `30.0` | Request timeout in seconds |

**Methods:**

```python
result = embedder.embed(text: str) -> EmbeddingResult
# Generates embedding for a single text string.
#
# Returns EmbeddingResult:
#   .embedding   list[float]
#   .model       str
#   .prompt_tokens  int | None
```

```python
results = embedder.embed_batch(texts: list[str]) -> list[EmbeddingResult]
# Batch embedding via Ollama /api/embed.
```

```python
available = embedder.is_available() -> bool
# Health check — returns True if Ollama is reachable.
```

```python
embedder.close() -> None
# Close HTTP client.
```

**Module-level helpers:**

```python
get_embedder() -> OllamaEmbedder  # Returns module singleton
set_embedder(embedder: OllamaEmbedder) -> None  # Replace singleton
```

---

### TierManager

**File:** `src/riks_context_engine/memory/tier_manager.py`

```python
from riks_context_engine.memory.tier_manager import TierManager, TierConfig
```

```python
tier_manager = TierManager(
    episodic: EpisodicMemory,
    semantic: SemanticMemory,
    procedural: ProceduralMemory,
    config: TierConfig | None = None,
)
```

**TierConfig defaults:**

| Attribute | Default | Description |
|-----------|---------|-------------|
| `promote_threshold` | `5` | Access count threshold for episodic → semantic promotion |
| `demote_threshold` | `0` | Min access count before demotion (0 = never demote) |
| `max_episodic` | `1000` | Max episodic entries before pruning |
| `check_interval_accesses` | `10` | Run `auto_tier()` every N cumulative accesses (0 = disabled) |

**Methods:**

```python
stats = tier_manager.auto_tier() -> dict[str, int]
# Runs one tiering cycle.
# Returns {"promoted": N, "demoted": N}
#
# Promotion: episodic entries with access_count > promote_threshold → semantic
# Demotion: semantic entries with access_count < demote_threshold → episodic
```

```python
tier_manager.record_access(memory_type: MemoryType, entry_id: str) -> None
# Records an access and triggers auto_tier() if check_interval reached.
```

---

## Context Window

### ImportanceScorer

**File:** `src/riks_context_engine/context/manager.py`

```python
from riks_context_engine.context.manager import ImportanceScorer
```

**Methods:**

```python
score, dims = ImportanceScorer.score(content: str, role: str) -> tuple[float, dict[str, float]]
# Returns (overall_score 0.0-1.0, dimension_scores dict)
#
# Dimension weights:
#   user_mentions    : 0.35  (user preferences, explicit mentions)
#   new_information : 0.25  (facts, results, errors)
#   decisions       : 0.25  (commitments, choices)
#   tool_result     : 0.15  (tool outputs)
```

```python
score = ImportanceScorer.auto_importance(content: str, role: str) -> float
# Convenience: returns just the overall score.
```

---

### ContextMessage

**File:** `src/riks_context_engine/context/manager.py`

```python
from riks_context_engine.context.manager import ContextMessage
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Auto-generated unique ID |
| `role` | `str` | `"user"`, `"assistant"`, `"system"`, or `"tool"` |
| `content` | `str` | Message text |
| `timestamp` | `datetime` | UTC creation time |
| `importance` | `float` | 0.0–1.0 score |
| `tokens` | `int` | Estimated token count |
| `is_grounding` | `bool` | True for user preferences / active projects |
| `is_pruned` | `bool` | True if removed from active context |
| `importance_dims` | `dict[str, float]` | Per-dimension breakdown |
| `priority_tier` | `int` | 0–3 (0=never prune, 3=first pruned) |

**Methods:**

```python
msg.should_preserve() -> bool
# Returns True if is_grounding or priority_tier == 0.

msg.pruning_score() -> float
# Lower score = more likely to be pruned.
# Score = -(importance * 100) - (tokens / 1000)
```

---

### ContextWindowManager

**File:** `src/riks_context_engine/context/manager.py`

```python
from riks_context_engine.context import ContextWindowManager
# or
from riks_context_engine.context.manager import ContextWindowManager
```

```python
ctx = ContextWindowManager(max_tokens: int = 180_000, model: str = "mini-max")
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_tokens` | `int` | `180_000` | Max context window capacity |
| `model` | `str` | `"mini-max"` | Model name for token estimation |

**Methods:**

```python
msg = ctx.add(
    role: str,
    content: str,
    importance: float = 0.5,
    is_grounding: bool = False,
    priority_tier: int = 2,
) -> ContextMessage
# Adds message and triggers pruning if needed.
```

```python
msg = ctx.auto_score_and_add(
    role: str,
    content: str,
    is_grounding: bool = False,
    priority_tier: int = 2,
) -> ContextMessage
# Adds message with auto-calculated importance via ImportanceScorer.
```

```python
messages = ctx.get_messages(include_pruned: bool = False) -> list[ContextMessage]
```

```python
active_tokens = ctx.get_active_tokens() -> int
# Total tokens of non-pruned messages.
```

```python
remaining = ctx.tokens_remaining() -> int
# Usable tokens remaining (max_tokens - 2*512 buffer - active_tokens).
```

```python
needs_prune = ctx.needs_pruning() -> bool
```

```python
valid, score = ctx.validate_coherence() -> tuple[bool, float]
# is_valid: no orphaned assistant responses, no grounding lost
# coherence_score: 0.0–1.0
```

```python
summary = ctx.get_summary() -> dict
# {
#   "max_tokens", "usable_tokens", "current_tokens",
#   "active_messages", "pruned_messages", "tokens_remaining",
#   "usage_percent", "pruning_events", "needs_pruning",
#   "coherence_valid", "coherence_score"
# }
```

```python
recommendation = ctx.get_pruning_recommendation() -> dict
# {
#   "level": "none" | "advisory" | "recommended" | "critical",
#   "usage_percent": float,
#   "tokens_to_free": int,
#   "tokens_remaining": int,
#   "tier_targets": list[int],
#   "urgent": bool,
# }
```

```python
ctx.reset() -> None
# Clears all messages and stats.
```

**Priority Tier Constants:**

| Constant | Value | Description |
|----------|-------|-------------|
| `TIER_0_PROTECTED` | `0` | System instructions — never pruned |
| `TIER_1_HIGH` | `1` | User preferences, tool results — rarely pruned |
| `TIER_2_MEDIUM` | `2` | Regular conversation — default tier |
| `TIER_3_LOW` | `3` | Low-importance messages — first to prune |

---

## Knowledge Graph

### Entity / EntityType

**File:** `src/riks_context_engine/graph/knowledge_graph.py`

```python
from riks_context_engine.graph.knowledge_graph import Entity, EntityType
```

#### `EntityType` Enum

| Value | Description |
|-------|-------------|
| `EntityType.PERSON` | Human individual |
| `EntityType.PROJECT` | Project or work item |
| `EntityType.CONCEPT` | Abstract concept or idea |
| `EntityType.EVENT` | Event or occurrence |
| `EntityType.TOOL` | Tool or software |
| `EntityType.DOCUMENT` | Document or artifact |

#### `Entity`

| Attribute | Type |
|-----------|------|
| `id` | `str` |
| `name` | `str` |
| `entity_type` | `EntityType` |
| `properties` | `dict` |
| `created_at` | `datetime` |
| `last_updated` | `datetime` |

---

### Relationship / RelationshipType

```python
from riks_context_engine.graph.knowledge_graph import Relationship, RelationshipType
```

#### `RelationshipType` Enum

| Value | Description |
|-------|-------------|
| `RelationshipType.WORKS_WITH` | Collaboration |
| `RelationshipType.DEPENDS_ON` | Dependency |
| `RelationshipType.USES` | Tool or resource usage |
| `RelationshipType.PARTICIPATED_IN` | Event participation |
| `RelationshipType.KNOWS_ABOUT` | Knowledge about a concept |
| `RelationshipType.RELATED_TO` | General relation |

#### `Relationship`

| Attribute | Type |
|-----------|------|
| `id` | `str` |
| `from_entity_id` | `str` |
| `to_entity_id` | `str` |
| `relationship_type` | `RelationshipType` |
| `properties` | `dict` |
| `confidence` | `float` (0.0–1.0) |
| `created_at` | `datetime` |

---

### KnowledgeGraph

**File:** `src/riks_context_engine/graph/knowledge_graph.py`

```python
from riks_context_engine.graph import KnowledgeGraph
# or
from riks_context_engine.graph.knowledge_graph import KnowledgeGraph
```

```python
graph = KnowledgeGraph(db_path: str | None = None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `"data/knowledge_graph.db"` | Path to SQLite database |

**Methods:**

```python
entity = graph.add_entity(
    name: str,
    entity_type: EntityType,
    properties: dict | None = None,
) -> Entity
```

```python
rel = graph.relate(
    from_entity: Entity,
    to_entity: Entity,
    relationship_type: RelationshipType,
    confidence: float = 1.0,
) -> Relationship
```

```python
results = graph.query(
    entity_name: str | None = None,
    relationship_type: RelationshipType | None = None,
) -> list[Entity | Relationship]
# Partial match on entity name; exact match on relationship type.
```

```python
connections = graph.expand(entity_id: str, depth: int = 1) -> list[tuple[Entity, Relationship]]
# BFS traversal from entity up to `depth` hops.
# Returns list of (connected_entity, relationship).
```

```python
path = graph.find_path(
    from_entity_id: str,
    to_entity_id: str,
    max_depth: int = 3,
) -> list[Relationship] | None
# BFS pathfinding. Returns relationship chain or None.
```

```python
entity = graph.get_entity(entity_id: str) -> Entity | None
```

```python
rels = graph.get_relationships(entity_id: str) -> list[Relationship]
```

```python
results = graph.semantic_search(
    query: str,
    top_k: int = 5,
    embedder: Any | None = None,
    score_threshold: float = 0.0,
) -> list[tuple[Entity, float]]
# Vector similarity search using cosine similarity.
# Falls back to keyword search if embedding service unavailable.
```

---

## Task Decomposition

### Task / TaskStatus

**File:** `src/riks_context_engine/tasks/decomposer.py`

```python
from riks_context_engine.tasks.decomposer import Task, TaskStatus
```

#### `TaskStatus` Enum

| Value | Description |
|-------|-------------|
| `TaskStatus.PENDING` | Not yet executed |
| `TaskStatus.RUNNING` | Currently executing |
| `TaskStatus.DONE` | Successfully completed |
| `TaskStatus.FAILED` | Execution failed |
| `TaskStatus.SKIPPED` | Skipped due to dependency failure |

#### `Task`

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique identifier |
| `name` | `str` | Human-readable name |
| `description` | `str` | Detailed description |
| `status` | `TaskStatus` | Current status |
| `dependencies` | `list[str]` | Task IDs that must complete first |
| `parallel_group` | `str \| None` | Group ID for parallel execution |
| `success_criteria` | `str \| None` | What constitutes success |
| `rollback_steps` | `list[str]` | Steps to undo this task |
| `created_at` | `datetime` | |
| `completed_at` | `datetime \| None` | |
| `retry_count` | `int` | Number of retries |

**Methods:**

```python
task.mark_done() -> None
task.mark_failed() -> None
task.mark_running() -> None
task.can_execute(completed_task_ids: set[str]) -> bool
```

---

### TaskGraph

```python
from riks_context_engine.tasks.decomposer import TaskGraph
```

```python
graph = TaskGraph(goal: str, tasks: list[Task] = field(default_factory=list))
```

**Methods:**

```python
task = graph.get_task(task_id: str) -> Task | None
```

```python
ready = graph.get_ready_tasks(completed: set[str]) -> list[Task]
# Tasks that are PENDING and have all dependencies satisfied.
```

```python
groups = graph.get_parallel_groups() -> dict[str, list[Task]]
# Tasks grouped by parallel_group for concurrent execution.
```

---

### TaskDecomposer

**File:** `src/riks_context_engine/tasks/decomposer.py`

```python
from riks_context_engine.tasks.decomposer import TaskDecomposer
```

```python
decomposer = TaskDecomposer(llm_provider: str = "ollama")
```

**Methods:**

```python
graph = decomposer.decompose(goal: str) -> TaskGraph
# Parses natural language goal into a TaskGraph with dependencies.
# Pattern-based extraction (not LLM-dependent).
```

```python
plan = decomposer.plan_execution(graph: TaskGraph) -> list[list[Task]]
# Returns execution batches respecting dependencies.
# Each batch = list of tasks that can run in parallel.
```

```python
valid, error = decomposer.validate_graph(graph: TaskGraph) -> tuple[bool, str | None]
# Checks for cycles (DFS) and missing dependencies.
```

```python
graph = decomposer.execute(graph: TaskGraph) -> TaskGraph
# Executes task graph marking tasks as RUNNING → DONE.
# (Stub implementation — real execution requires integration.)
```

---

## Reflection

### Lesson / Severity

**File:** `src/riks_context_engine/reflection/analyzer.py`

```python
from riks_context_engine.reflection.analyzer import Lesson
```

#### Lesson Categories

| Category | Pattern Examples |
|----------|-----------------|
| `tool-use` | tool fail, function error, missing parameter |
| `context-management` | context overflow, token limit, forgot preference |
| `task-planning` | wrong order, missed step, dependency broken |
| `communication` | unclear request, misunderstood intent |
| `security` | injection, exposure, unauthorized |
| `general` | fallback |

#### Severity Levels

| Level | Triggers |
|-------|---------|
| `info` | Default |
| `warning` | mistake, wrong, fail, warning |
| `critical` | critical, security, breach, data loss |

#### `Lesson`

| Attribute | Type |
|-----------|------|
| `id` | `str` |
| `category` | `str` |
| `observation` | `str` |
| `lesson_text` | `str` |
| `severity` | `str` (`info` \| `warning` \| `critical`) |
| `occurrence_count` | `int` |
| `first_seen` | `datetime` |
| `last_seen` | `datetime` |
| `resolved` | `bool` |

---

### ReflectionReport

```python
from riks_context_engine.reflection.analyzer import ReflectionReport
```

| Attribute | Type |
|-----------|------|
| `interaction_id` | `str` |
| `went_well` | `list[str]` |
| `went_wrong` | `list[str]` |
| `missing_info` | `list[str]` |
| `lessons` | `list[Lesson]` |
| `timestamp` | `datetime` |

---

### ReflectionAnalyzer

**File:** `src/riks_context_engine/reflection/analyzer.py`

```python
from riks_context_engine.reflection import ReflectionAnalyzer
# or
from riks_context_engine.reflection.analyzer import ReflectionAnalyzer
```

```python
reflection = ReflectionAnalyzer(semantic_memory: Any = None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `semantic_memory` | `Any` | `None` | SemanticMemory store for persisting successes |

**Methods:**

```python
report = reflection.analyze(
    interaction_id: str,
    conversation: list[dict],
) -> ReflectionReport
# Pattern-based analysis of a conversation.
# conversation = [{"role": str, "content": str}, ...]
```

```python
lessons = reflection.consult_before_task(task_description: str) -> list[Lesson]
# Returns up to 5 unresolved critical/warning lessons for task's categories.
```

```python
reflection.record_success(task_id: str, details: str) -> None
# Stores success in semantic memory if available.
```

```python
reflection.record_failure(
    task_id: str,
    error: str,
    root_cause: str | None = None,
) -> None
# Creates a new lesson from the failure.
```

```python
mistakes = reflection.track_mistake_frequency() -> dict[str, int]
# Returns {category: count} for all recorded failures.
```

```python
active = reflection.get_active_lessons() -> list[Lesson]
# All unresolved lessons.
```

```python
resolved = reflection.resolve_lesson(lesson_id: str) -> bool
# Marks a lesson as resolved.
```

---

## CLI

**Entry point:** `riks` (installed via `pip install -e .`)

```bash
riks --version
riks memory <action> [--type TYPE] [args...]
riks context <action> [args...]
riks task <goal> [--execute]
riks reflect --session SESSION_ID
```

### Commands

| Command | Description |
|---------|-------------|
| `riks --version` | Show version |
| `riks memory add --type episodic "content"` | Add memory entry |
| `riks memory query --type semantic "query"` | Query memories |
| `riks memory stats --type procedural` | Show storage statistics |
| `riks context stats` | Context window statistics |
| `riks context prune` | Trigger pruning |
| `riks context clear` | Clear context window |
| `riks task "goal description"` | Decompose goal into tasks |
| `riks reflect --session <id>` | Run reflection on session |

---

## Error Handling

### Custom Exceptions

| Exception | File | Raised When |
|-----------|------|-------------|
| `OllamaEmbeddingError` | `memory/embedding.py` | Ollama embedding API fails or is unreachable |

### Common Errors

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `ConnectionRefused` | Ollama not running | Start Ollama or set `OLLAMA_BASE_URL` |
| `JSONDecodeError` on load | Corrupted storage file | Backup and delete file; system rebuilds on write |
| `sqlite3.OperationalError` | Locked DB file | Only one writer at a time; use connection pooling |
| `KeyError` on query | Entry already deleted | Check return value for `None` before use |

---

## Type Aliases Summary

| Alias | Actual Type |
|-------|------------|
| `EpisodicEntry` | `dataclass` in `episodic.py` |
| `SemanticEntry` | `dataclass` in `semantic.py` |
| `Procedure` | `dataclass` in `procedural.py` |
| `EmbeddingResult` | `dataclass` in `embedding.py` |
| `TierConfig` | `dataclass` in `tier_manager.py` |
| `ContextMessage` | `dataclass` in `context/manager.py` |
| `ContextStats` | `dataclass` in `context/manager.py` |
| `Entity` | `dataclass` in `graph/knowledge_graph.py` |
| `Relationship` | `dataclass` in `graph/knowledge_graph.py` |
| `Task` | `dataclass` in `tasks/decomposer.py` |
| `TaskGraph` | `dataclass` in `tasks/decomposer.py` |
| `Lesson` | `dataclass` in `reflection/analyzer.py` |
| `ReflectionReport` | `dataclass` in `reflection/analyzer.py` |

---

_Built with 🗿 by [opsiton](https://github.com/vopsiton) for the Rik AI ecosystem._
