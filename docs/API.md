# Rik Context Engine — API Reference

> Full API documentation for `riks-context-engine` v0.2.0
>
> ⚠️ **This file (`docs/API.md`) is the single source of truth for API documentation.**
> The former `docs/API_REFERENCE.md` was merged here and removed (issue #125).

---

## Installation

```bash
pip install riks-context-engine
```

Or install from source:

```bash
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine
pip install -e ".[dev]"
```

---

## Package Entry Point

```python
from riks_context_engine import (
    EpisodicMemory,
    SemanticMemory,
    ProceduralMemory,
    ContextWindowManager,
)
from riks_context_engine.tasks import TaskDecomposer
from riks_context_engine.graph import KnowledgeGraph
from riks_context_engine.reflection import ReflectionAnalyzer
```

---

## Memory Modules

### `riks_context_engine.memory.base`

#### `MemoryType`

```python
class MemoryType(Enum):
    """Discriminator for the three memory tiers."""
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
```

#### `MemoryEntry`

Unified schema for all memory entries across tiers.

```python
@dataclass
class MemoryEntry:
    id: str                           # Unique ID prefixed by tier (e.g. "ep_123")
    type: MemoryType                  # Which tier this entry belongs to
    content: str                      # Human-readable content
    timestamp: datetime               # UTC creation time
    importance: float                 # 0.0–1.0 significance score
    embedding: list[float] | None     # Vector representation
    access_count: int                 # Number of retrievals
    last_accessed: datetime | None    # UTC last retrieval time
    metadata: dict[str, Any]          # Tier-specific extra fields
```

**Methods:**

```python
entry.record_access() -> None
    # Increment access_count, update last_accessed timestamp.

entry.to_dict() -> dict[str, Any]
    # Serialize to JSON-compatible dictionary.

entry.from_dict(data: dict[str, Any]) -> MemoryEntry
    # Classmethod: reconstruct from dictionary.
```

---

### `riks_context_engine.memory.episodic`

#### `EpisodicMemory`

Session-level, short-term memory store. Persists to `data/episodic.json`.

```python
class EpisodicMemory:
    def __init__(self, storage_path: str | None = None)
        # Args:
        #   storage_path: Override default path (default: "data/episodic.json")
```

**Methods:**

```python
mem.add(
    content: str,
    importance: float = 0.5,           # 0.0–1.0
    tags: list[str] | None = None,
    embedding: list[float] | None = None,
) -> EpisodicEntry
    # Add a new episodic memory entry. Persists to disk immediately.

mem.get(entry_id: str) -> EpisodicEntry | None
    # Retrieve entry by ID. Increments access_count and updates last_accessed.

mem.query(query: str, limit: int = 10) -> list[EpisodicEntry]
    # Keyword search across content and tags.
    # Results sorted by (importance desc, timestamp desc).

mem.prune(max_entries: int = 1000) -> int
    # Remove lowest-importance entries when limit exceeded.
    # Returns number of entries removed.

mem.delete(entry_id: str) -> bool
    # Delete entry by ID. Persists to disk immediately.

len(mem) -> int
    # Returns number of entries currently stored.
```

---

### `riks_context_engine.memory.semantic`

#### `SemanticMemory`

Long-term structured knowledge store. Persists to SQLite.

```python
class SemanticMemory:
    def __init__(
        self,
        db_path: str | None = None,    # Default: "data/semantic.db"
        embedder: Any | None = None,   # OllamaEmbedder instance
    )
```

**Methods:**

```python
sem.add(
    subject: str,
    predicate: str,
    object: str | None = None,
    confidence: float = 1.0,           # 0.0–1.0
    embedding: list[float] | None = None,
) -> SemanticEntry
    # Add a semantic knowledge triple (subject→predicate→object).
    # Example: sem.add("auth_service", "uses", "JWT RS256")

sem.get(entry_id: str) -> SemanticEntry | None
    # Retrieve by ID. Increments access_count.

sem.query(
    subject: str | None = None,
    predicate: str | None = None,
) -> list[SemanticEntry]
    # Filter by subject and/or predicate (partial, case-insensitive LIKE).

sem.recall(query: str) -> list[SemanticEntry]
    # Keyword search across subject, predicate, and object fields.

sem.delete(entry_id: str) -> bool
    # Delete by ID. Returns True if row was deleted.

sem.to_memory_entry(
    self,
) -> MemoryEntry
    # Convert SemanticEntry to generic MemoryEntry.

len(sem) -> int
    # Total number of entries in the database.
```

---

### `riks_context_engine.memory.procedural`

#### `ProceduralMemory`

Stores skills, workflows, and how-to knowledge. Persists to `data/procedural.json`.

```python
class ProceduralMemory:
    def __init__(self, storage_path: str | None = None)
        # Default: "data/procedural.json"
```

**Methods:**

```python
proc.store(
    name: str,
    description: str,
    steps: list[str],
    tags: list[str] | None = None,
) -> Procedure
    # Store a new procedure / skill.
    # Example:
    #   proc.store(
    #       name="Deploy to Production",
    #       description="Blue-green deployment via SSH",
    #       steps=["ssh prod-server", "cd /app", "docker-compose pull", ...]
    #   )

proc.get(proc_id: str) -> Procedure | None
    # Retrieve by ID. Increments use_count and updates last_used.

proc.recall(name: str) -> Procedure | None
    # Exact-match lookup by procedure name (case-insensitive).

proc.find(query: str) -> list[Procedure]
    # Search by name, description, or tags.
    # Results sorted by (use_count desc, success_rate desc).

proc.delete(proc_id: str) -> bool
    # Delete by ID.

proc.update_success_rate(proc_id: str, success: bool) -> bool
    # Update rolling success rate after execution.
    # Formula: new_rate = (old_rate * (n-1) + (1.0 if success else 0.0)) / n

proc.procedures: dict[str, Procedure]
    # Property: all procedures as dict.

len(proc) -> int
    # Number of stored procedures.
```

---

### `riks_context_engine.memory.embedding`

#### `OllamaEmbedder`

Generates vector embeddings via Ollama API.

```python
class OllamaEmbedder:
    def __init__(
        self,
        base_url: str | None = None,         # Default: http://localhost:11434
        model: str = "nomic-embed-text",
        timeout: float = 30.0,
    )
```

**Methods:**

```python
embedder.embed(text: str) -> EmbeddingResult
    # Generate embedding for single text.
    # Raises OllamaEmbeddingError on failure.

embedder.embed_batch(texts: list[str]) -> list[EmbeddingResult]
    # Batch embed multiple texts in one API call.

embedder.is_available() -> bool
    # Check if Ollama service is reachable.

embedder.close() -> None
    # Close the HTTP client.
```

**Module-level helpers:**

```python
get_embedder() -> OllamaEmbedder
    # Return (or create) the module-level singleton embedder.

set_embedder(embedder: OllamaEmbedder) -> None
    # Replace the module-level singleton (for custom embedder).
```

---

### `riks_context_engine.memory.tier_manager`

#### `TierManager`

Manages automatic promotion/demotion across episodic ↔ semantic tiers.

```python
class TierManager:
    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        procedural: ProceduralMemory,
        config: TierConfig | None = None,
    )
```

**Methods:**

```python
tm.auto_tier() -> dict[str, int]
    # Run one tiering cycle.
    # Returns: {"promoted": N, "demoted": N}
    #
    # Promotion: episodic entries with access_count > promote_threshold
    #            are moved to semantic memory.
    # Demotion:  semantic entries with access_count < demote_threshold
    #            are moved back to episodic (if threshold > 0).

tm.record_access(memory_type: MemoryType, entry_id: str) -> None
    # Record an access and optionally trigger auto_tier.
    # auto_tier runs when cumulative accesses >= check_interval_accesses.
```

---

## Context Module

### `riks_context_engine.context.manager`

#### `ImportanceScorer`

Auto-scores message importance using content analysis.

```python
class ImportanceScorer:
    @classmethod
    def score(cls, content: str, role: str) -> tuple[float, dict[str, float]]
        # Returns (overall_score 0.0–1.0, dimension_scores dict)
        # Dimensions: user_mentions, new_information, decisions, tool_result

    @classmethod
    def auto_importance(cls, content: str, role: str) -> float
        # Convenience: returns just the overall score.
```

**Dimension weights:**

| Dimension | Weight | What it detects |
|-----------|--------|----------------|
| `user_mentions` | 35% | User preferences, stated facts |
| `decisions` | 25% | Commitments, choices, "will do" |
| `new_information` | 25% | Novel facts, results, errors, IPs |
| `tool_result` | 15% | Tool outputs (role=tool → 0.8) |

---

#### `ContextWindowManager`

Intelligent context window management with automatic pruning.

```python
class ContextWindowManager:
    def __init__(
        self,
        max_tokens: int = 180_000,
        model: str = "mini-max",
    )
```

**Methods:**

```python
ctx.add(
    role: str,                         # "user" | "assistant" | "system" | "tool"
    content: str,
    importance: float = 0.5,           # 0.0–1.0
    is_grounding: bool = False,        # True = never prune (user preferences)
    priority_tier: int = 2,            # 0=protected, 1=high, 2=medium, 3=low
) -> ContextMessage

ctx.auto_score_and_add(
    role: str,
    content: str,
    is_grounding: bool = False,
    priority_tier: int = 2,
) -> ContextMessage
    # Add message with automatic importance scoring via ImportanceScorer.

ctx.get_messages(include_pruned: bool = False) -> list[ContextMessage]
    # Get all messages. Set include_pruned=True to see pruned ones too.

ctx.get_active_tokens() -> int
    # Total tokens of non-pruned messages.

ctx.tokens_remaining() -> int
    # Tokens left before forced pruning (may be negative).

ctx.needs_pruning() -> bool
    # True if tokens_remaining() < 0.

ctx.validate_coherence() -> tuple[bool, float]
    # Returns (is_valid, coherence_score 0.0–1.0)
    # Checks: no orphaned responses, grounding preserved, no excessive same-role chains.

ctx.get_usage_percent() -> float
    # Current usage as percentage of max_tokens.

ctx.get_pruning_recommendation() -> dict
    # Returns: {level, usage_percent, tokens_to_free, tokens_remaining, tier_targets, urgent}

ctx.get_summary() -> dict
    # Full context window stats for debugging/logging.

ctx.mark_below_threshold(threshold: int = 512) -> list[ContextMessage]
    # Return messages that fit within remaining token space.

ctx.reset() -> None
    # Clear all messages and reset stats.
```

---

## Tasks Module

### `riks_context_engine.tasks.decomposer`

#### `TaskDecomposer`

Decomposes natural language goals into dependency-respecting task graphs.

```python
class TaskDecomposer:
    def __init__(self, llm_provider: str = "ollama")
```

**Methods:**

```python
decomposer.decompose(goal: str) -> TaskGraph
    # Decompose goal text into a TaskGraph.
    # Uses keyword splitting by "and" delimiters.
    # Infers dependencies via infer_dependencies().

decomposer.plan_execution(graph: TaskGraph) -> list[list[Task]]
    # Returns batches of tasks ready to execute.
    # Each batch = tasks with all dependencies satisfied.

decomposer.execute(graph: TaskGraph) -> TaskGraph
    # Execute task graph (marks tasks RUNNING → DONE).

decomposer.validate_graph(graph: TaskGraph) -> tuple[bool, str | None]
    # Check for cycles and missing dependencies.
```

**Supporting classes:**

```python
class Task:
    id: str
    name: str
    description: str
    status: TaskStatus           # PENDING | RUNNING | DONE | FAILED | SKIPPED
    dependencies: list[str]     # Task IDs that must complete first
    parallel_group: str | None   # Tasks with same group can run concurrently
    success_criteria: str | None
    rollback_steps: list[str]
    created_at: datetime
    completed_at: datetime | None
    retry_count: int

    def can_execute(self, completed_task_ids: set[str]) -> bool
        # True if all dependencies are in completed_task_ids.

    def mark_done() / mark_failed() / mark_running()

class TaskGraph:
    goal: str
    tasks: list[Task]
    created_at: datetime

    def get_task(task_id: str) -> Task | None
    def get_ready_tasks(completed: set[str]) -> list[Task]
    def get_parallel_groups() -> dict[str, list[Task]]
```

---

## Graph Module

### `riks_context_engine.graph.knowledge_graph`

#### `KnowledgeGraph`

Entity-relationship knowledge graph with semantic search.

```python
class KnowledgeGraph:
    def __init__(self, db_path: str | None = None)
        # Default: "data/knowledge_graph.db" (SQLite)
```

**Methods:**

```python
kg.add_entity(
    name: str,
    entity_type: EntityType,       # PERSON | PROJECT | CONCEPT | EVENT | TOOL | DOCUMENT
    properties: dict | None = None,
) -> Entity

kg.relate(
    from_entity: Entity,
    to_entity: Entity,
    relationship_type: RelationshipType,
    # WORKS_WITH | DEPENDS_ON | USES | PARTICIPATED_IN | KNOWS_ABOUT | RELATED_TO
    confidence: float = 1.0,
) -> Relationship

kg.query(
    entity_name: str | None = None,
    relationship_type: RelationshipType | None = None,
) -> list[Entity | Relationship]
    # Filter by entity name or relationship type.

kg.expand(entity_id: str, depth: int = 1) -> list[tuple[Entity, Relationship]]
    # Traverse from entity outward N hops.
    # Returns (connected_entity, relationship) tuples.

kg.get_entity(entity_id: str) -> Entity | None

kg.get_relationships(entity_id: str) -> list[Relationship]
    # All relationships involving this entity.

kg.find_path(
    from_entity_id: str,
    to_entity_id: str,
    max_depth: int = 3,
) -> list[Relationship] | None
    # BFS pathfinding. Returns relationship chain or None if no path.

kg.semantic_search(
    query: str,
    top_k: int = 5,
    embedder: EmbedderProtocol | None = None,
    score_threshold: float = 0.0,
) -> list[tuple[Entity, float]]
    # Vector similarity search across all entities.
    # Falls back to keyword match if embedder unavailable.
```

---

## Reflection Module

### `riks_context_engine.reflection.analyzer`

#### `ReflectionAnalyzer`

Self-improvement loop that learns from interactions.

```python
class ReflectionAnalyzer:
    def __init__(self, semantic_memory: SemanticMemory | None = None)
```

**Methods:**

```python
analyzer.analyze(
    interaction_id: str,
    conversation: list[dict],  # [{"role": str, "content": str}, ...]
) -> ReflectionReport
    # Analyze conversation after the fact.
    # Extracts went_well, went_wrong, missing_info, and Lessons.

analyzer.consult_before_task(task_description: str) -> list[Lesson]
    # Before starting a task, check for related past failures.
    # Returns up to 5 unresolved critical/warning lessons.

analyzer.record_success(task_id: str, details: str) -> None
    # Store successful task completion.

analyzer.record_failure(
    task_id: str,
    error: str,
    root_cause: str | None = None,
) -> None
    # Store failed task with error and optional root cause.

analyzer.track_mistake_frequency() -> dict[str, int]
    # Returns: {"tool-use": 5, "context-management": 3, ...}

analyzer.get_active_lessons() -> list[Lesson]
    # All unresolved lessons.

analyzer.resolve_lesson(lesson_id: str) -> bool
    # Mark lesson as resolved. Returns True if found.
```

**Supporting classes:**

```python
class Lesson:
    id: str
    category: str      # tool-use | context-management | task-planning | ...
    observation: str  # What was observed
    lesson_text: str   # What to do differently
    severity: str      # info | warning | critical
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    resolved: bool

class ReflectionReport:
    interaction_id: str
    went_well: list[str]
    went_wrong: list[str]
    missing_info: list[str]
    lessons: list[Lesson]
    timestamp: datetime
```

---

## HTTP API (FastAPI server)

> Source: `src/riks_context_engine/api/server.py` (FastAPI app, spec version 0.4.0).
> Run the server with `python -m riks_context_engine.api.server` or via Docker.
> Interactive spec: `http://localhost:8000/docs` (Swagger) / `/redoc`.
>
> This section is the foundation for **spec-driven generation** (issue #123):
> the endpoint table below is produced from `app.openapi()` by
> `scripts/generate_api_docs.py`.
> ```bash
> uv run python scripts/generate_api_docs.py            # print table to stdout
> uv run python scripts/generate_api_docs.py --write    # regenerate the table in this file
> ```

### Authentication & tenant isolation

- **API key:** when the `API_KEY` environment variable is set, protected paths
  require the `X-API-Key` header (otherwise requests pass through — e.g. local dev).
- **Tenant header:** tenant-scoped endpoints require the `X-Tenant-Id` header.
  Missing, empty, or malformed (bad chars / >64 chars) values → `401`.
- **Rate limiting:** sliding-window limiter may return `429` with a
  `Retry-After` header (issue #99).

### Endpoint overview (auto-generated — do not edit by hand)

<!-- AUTO:HTTP-ENDPOINTS:BEGIN (generated by scripts/generate_api_docs.py — do not edit) -->
| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/` | X-API-Key, X-Tenant-Id (if API_KEY set) | Root |
| GET | `/api/v1/context/messages` | X-API-Key, X-Tenant-Id (if API_KEY set) | Context List Messages |
| GET | `/api/v1/context/summary` | X-API-Key, X-Tenant-Id (if API_KEY set) | Context Summary |
| GET | `/api/v1/memory/export` | X-API-Key, X-Tenant-Id (if API_KEY set) | Export Memory Api |
| GET | `/health` | none | Health |
| GET | `/models` | X-API-Key, X-Tenant-Id (if API_KEY set) | List Models |
| POST | `/api/chat` | X-API-Key, X-Tenant-Id | Chat |
| POST | `/api/v1/context/messages` | X-API-Key, X-Tenant-Id | Context Add Message |
| POST | `/api/v1/memory/import` | X-API-Key, X-Tenant-Id | Import Memory Api |
<!-- AUTO:HTTP-ENDPOINTS:END -->

### Endpoints

#### `GET /health`

| Item | Detail |
|------|--------|
| Response | `200 {"status": "ok"}` |

#### `GET /models`

List available chat models.

- **Response:** `200 {"models": ["gemma4-31b-it", "qwen3.5-9b", "gemma-4-31b", "minimax-m2.7"]}`

#### `POST /api/chat`

| Item | Detail |
|------|--------|
| Request body | `{"message": str, "model": str \| null}` (default model: `gemma4-31b-it`) |
| Errors | `400` unknown model |
| Response | `200 {"response": str, "model": str}` |

#### `GET /`

Serves the UI (`UI_PATH` env var, default `ui/index.html`).

---

#### Tenant-scoped context endpoints (#102)

All three endpoints are isolated per tenant via `X-Tenant-Id`.

#### `POST /api/v1/context/messages`

Append a message to the caller's tenant context window.

**Request body** (`ContextAddRequest`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `role` | `str` | `"user"` | `user` \| `assistant` \| `system` (other values → `400`) |
| `content` | `str` | required | Message content |
| `importance` | `float` | `0.5` | Significance score, `0.0`–`1.0` |

**Response:** `200`

```json
{
  "message_id": "ctx_…",
  "role": "user",
  "tokens": 12,
  "status": "added"
}
```

#### `GET /api/v1/context/messages`

List the caller's tenant context window (pruned messages excluded).
Isolated per tenant.

**Response:** `200` — array of:

```json
{
  "id": "ctx_…",
  "role": "user",
  "content": "…",
  "timestamp": "2026-08-18T10:00:00+00:00",
  "importance": 0.5,
  "tokens": 12
}
```

#### `GET /api/v1/context/summary`

Context window stats for the caller's tenant only.

**Response:** `200`

```json
{
  "current_tokens": 1024,
  "max_tokens": 8192,
  "messages_count": 12,
  "active_messages_count": 10,
  "pruning_count": 2,
  "last_prune_timestamp": "2026-08-18T09:59:00+00:00"
}
```

(`last_prune_timestamp` is `null` until the first prune.)

---

#### Memory export / import endpoints

#### `GET /api/v1/memory/export`

Export memory tiers as JSON or YAML manifest.

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| `types` | `str` | Comma-separated: `episodic,semantic,procedural` (default: all) |
| `format` | `str` | `json` (default) or `yaml` |
| `date_from` / `date_to` | `datetime` | Time filter |
| `tags` | `str` | Comma-separated tags filter |

**Response:** `200`

```json
{
  "export_id": "exp_…",
  "schema_version": "1.0",
  "counts": {"episodic": 3, "semantic": 5, "procedural": 1},
  "data": "<serialized manifest>"
}
```

#### `POST /api/v1/memory/import`

Import memory tiers from a JSON or YAML manifest.

**Request body** (`MemoryImportRequest`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | required | JSON or YAML manifest content |
| `format` | `str` | `"json"` | `json` or `yaml` |
| `merge` | `bool` | `true` | `true`: skip duplicate IDs; `false`: replace all |

**Response:** `200`

```json
{
  "imported": {"episodic": 3, "semantic": 5, "procedural": 1},
  "schema_version": "1.0"
}
```

**Errors:** `400` invalid manifest.

#### `WS /ws/v1/context/stream`

WebSocket endpoint for streaming context events to the UI.

---

## CLI

```bash
# Show version
riks --version

# Memory operations
riks memory add --type episodic "User prefers Turkish"
riks memory query --type semantic "auth"
riks memory stats

# Context operations
riks context stats
riks context prune
riks context clear

# Task decomposition
riks task "Setup auth, build image, deploy to prod" --execute

# Reflection
riks reflect --session sess_123
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `gemma4-31b-q4` | Default LLM for decomposition |
| `CHROMA_HOST` | `localhost` | ChromaDB server |
| `DATA_DIR` | `/app/data` | Storage root directory |

### Custom Embedder

```python
from riks_context_engine.memory.embedding import set_embedder, OllamaEmbedder

# Use a different model
custom = OllamaEmbedder(model="llama3.2:latest")
set_embedder(custom)
```

---

## Exceptions

```python
class OllamaEmbeddingError(Exception)
    # Raised when Ollama embed() fails (connection, HTTP error, bad response).
```

All other errors are standard Python exceptions (`ValueError`, `KeyError`, `sqlite3.Error`, etc.).
