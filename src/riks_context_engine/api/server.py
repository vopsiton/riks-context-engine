"""FastAPI server for Rik's Context Engine.

Exposes the core engine capabilities via a REST API:
- Memory CRUD (episodic, semantic, procedural)
- Context window management
- Knowledge graph queries
- Task decomposition
- Reflection analysis

Run with:
    uvicorn riks_context_engine.api.server:app --host 0.0.0.0 --port 8000
Or via CLI:
    riks serve --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from riks_context_engine.context.manager import ContextMessage, ContextWindowManager
from riks_context_engine.graph.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeGraph,
    Relationship,
    RelationshipType,
)
from riks_context_engine.memory.base import MemoryEntry, MemoryType
from riks_context_engine.memory.episodic import EpisodicEntry, EpisodicMemory
from riks_context_engine.memory.procedural import Procedure, ProceduralMemory
from riks_context_engine.memory.semantic import SemanticEntry, SemanticMemory
from riks_context_engine.reflection.analyzer import (
    Lesson,
    ReflectionReport,
    detect_category,
    extract_severity,
)
from riks_context_engine.tasks.decomposer import Task, TaskGraph, TaskStatus


# ─── Lifespan ────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Global instances (initialized on startup)
_context_mgr: ContextWindowManager | None = None
_episodic_mem: EpisodicMemory | None = None
_semantic_mem: SemanticMemory | None = None
_procedural_mem: ProceduralMemory | None = None
_knowledge_graph: KnowledgeGraph | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _context_mgr, _episodic_mem, _semantic_mem, _procedural_mem, _knowledge_graph
    _context_mgr = ContextWindowManager()
    _episodic_mem = EpisodicMemory(storage_path=str(DATA_DIR / "episodic.json"))
    _semantic_mem = SemanticMemory(db_path=str(DATA_DIR / "semantic.db"))
    _procedural_mem = ProceduralMemory(storage_path=str(DATA_DIR / "procedural.json"))
    _knowledge_graph = KnowledgeGraph(db_path=str(DATA_DIR / "knowledge_graph.db"))
    _knowledge_graph.load()
    # Load persisted context history on startup
    _context_mgr.load(str(DATA_DIR / "context_history.json"))
    yield
    # Persist context history on shutdown
    if _context_mgr is not None:
        _context_mgr.save(str(DATA_DIR / "context_history.json"))
    # Cleanup
    _context_mgr = None
    _episodic_mem = None
    _semantic_mem = None
    _procedural_mem = None
    _knowledge_graph = None


app = FastAPI(
    title="Rik's Context Engine API",
    description="AI context and memory management framework - REST API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response Models ───────────────────────────────────────────────

class MessageCreate(BaseModel):
    role: str = Field(..., description="Message role: 'user', 'assistant', 'system'")
    content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class MessageResponse(BaseModel):
    role: str
    content: str
    tokens: int
    importance: float
    id: str


class ContextStatsResponse(BaseModel):
    total_messages: int
    total_tokens: int
    tokens_remaining: int
    usage_percent: float
    needs_pruning: bool
    coherence_score: float | None


class EpisodicEntryResponse(BaseModel):
    id: str
    content: str
    importance: float
    tags: list[str]
    timestamp: str


class SemanticEntryResponse(BaseModel):
    id: str
    subject: str
    predicate: str
    object: str | None
    confidence: float
    access_count: int
    created_at: str


class ProcedureResponse(BaseModel):
    id: str
    name: str
    description: str
    steps: list[str]
    use_count: int
    success_rate: float
    tags: list[str]


class EntityCreate(BaseModel):
    name: str
    entity_type: str  # "person", "project", "concept", "event", "tool", "document"
    properties: dict = Field(default_factory=dict)


class RelationshipCreate(BaseModel):
    from_entity_name: str
    to_entity_name: str
    relationship_type: str  # "works_with", "depends_on", "uses", etc.
    confidence: float = 1.0


class TaskCreate(BaseModel):
    goal: str
    execute: bool = False


class TaskResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    dependencies: list[str]


class ReflectionAnalyzeRequest(BaseModel):
    interaction_id: str
    went_well: list[str] = []
    went_wrong: list[str] = []
    missing_info: list[str] = []


class LessonResponse(BaseModel):
    id: str
    category: str
    observation: str
    lesson_text: str
    severity: str
    occurrence_count: int
    resolved: bool


# ─── Health ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "riks-context-engine"}


# ─── Context Window ──────────────────────────────────────────────────────────

@app.get("/context/stats", response_model=ContextStatsResponse)
async def context_stats():
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    stats = _context_mgr.stats
    return ContextStatsResponse(
        total_messages=stats.messages_count,
        total_tokens=stats.current_tokens,
        tokens_remaining=_context_mgr.tokens_remaining(),
        usage_percent=round(_context_mgr.get_active_tokens() / _context_mgr.usable_tokens * 100, 1) if _context_mgr.usable_tokens > 0 else 0,
        needs_pruning=_context_mgr.needs_pruning(),
        coherence_score=_context_mgr.validate_coherence() if _context_mgr.messages else None,
    )


@app.post("/context/messages", response_model=MessageResponse)
async def add_message(msg: MessageCreate):
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    ctx_msg = _context_mgr.add(
        role=msg.role,
        content=msg.content,
        importance=msg.importance,
    )
    return MessageResponse(
        role=ctx_msg.role,
        content=ctx_msg.content,
        tokens=ctx_msg.tokens,
        importance=ctx_msg.importance,
        id=ctx_msg.id,
    )


@app.get("/context/messages", response_model=list[MessageResponse])
async def get_messages(include_pruned: bool = False):
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    msgs = _context_mgr.get_messages(include_pruned=include_pruned)
    return [
        MessageResponse(
            role=m.role,
            content=m.content,
            tokens=_context_mgr._estimate_tokens(m.content),
            importance=m.importance,
            id=m.id,
        )
        for m in msgs
    ]


@app.post("/context/prune")
async def prune_context():
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    rec = _context_mgr.get_pruning_recommendation()
    pruned = _context_mgr.prune()
    return {"pruned_count": pruned, "recommendation": rec}


@app.delete("/context/reset")
async def reset_context():
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    _context_mgr.reset()
    return {"status": "reset"}


@app.post("/context/history/save")
async def save_context_history():
    """Manually persist context window history to disk."""
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    path = _context_mgr.save(str(DATA_DIR / "context_history.json"))
    return {"status": "saved", "path": path}


@app.get("/context/history/load")
async def load_context_history():
    """Load context window history from disk."""
    if _context_mgr is None:
        raise HTTPException(503, "Context manager not initialized")
    count = _context_mgr.load(str(DATA_DIR / "context_history.json"))
    return {"status": "loaded", "messages_loaded": count}


# ─── Memory ──────────────────────────────────────────────────────────────────

## Episodic

@app.get("/memory/episodic", response_model=list[EpisodicEntryResponse])
async def list_episodic(limit: int = Query(default=50, le=500)):
    if _episodic_mem is None:
        raise HTTPException(503, "Episodic memory not initialized")
    entries = list(_episodic_mem._entries.values())[-limit:]
    return [
        EpisodicEntryResponse(
            id=e.id,
            content=e.content,
            importance=e.importance,
            tags=e.tags or [],
            timestamp=e.timestamp.isoformat(),
        )
        for e in reversed(entries)
    ]


@app.post("/memory/episodic", response_model=EpisodicEntryResponse)
async def add_episodic(content: str, importance: float = 0.5, tags: str = ""):
    if _episodic_mem is None:
        raise HTTPException(503, "Episodic memory not initialized")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    entry = _episodic_mem.add(content=content, importance=importance, tags=tag_list)
    return EpisodicEntryResponse(
        id=entry.id,
        content=entry.content,
        importance=entry.importance,
        tags=entry.tags or [],
        timestamp=entry.timestamp.isoformat(),
    )


@app.get("/memory/episodic/search", response_model=list[EpisodicEntryResponse])
async def search_episodic(q: str = Query(...), limit: int = 10):
    if _episodic_mem is None:
        raise HTTPException(503, "Episodic memory not initialized")
    results = _episodic_mem.query(q, limit=limit)
    return [
        EpisodicEntryResponse(
            id=e.id,
            content=e.content,
            importance=e.importance,
            tags=e.tags or [],
            timestamp=e.timestamp.isoformat(),
        )
        for e in results
    ]


@app.delete("/memory/episodic/{entry_id}")
async def delete_episodic(entry_id: str):
    if _episodic_mem is None:
        raise HTTPException(503, "Episodic memory not initialized")
    deleted = _episodic_mem.delete(entry_id)
    if not deleted:
        raise HTTPException(404, f"Entry {entry_id} not found")
    return {"deleted": entry_id}


## Semantic

@app.get("/memory/semantic", response_model=list[SemanticEntryResponse])
async def list_semantic(subject: str | None = None, predicate: str | None = None):
    if _semantic_mem is None:
        raise HTTPException(503, "Semantic memory not initialized")
    entries = _semantic_mem.query(subject=subject, predicate=predicate)
    return [
        SemanticEntryResponse(
            id=e.id,
            subject=e.subject,
            predicate=e.predicate,
            object=e.object,
            confidence=e.confidence,
            access_count=e.access_count,
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]


@app.post("/memory/semantic", response_model=SemanticEntryResponse)
async def add_semantic(subject: str, predicate: str, object: str | None = None, confidence: float = 1.0):
    if _semantic_mem is None:
        raise HTTPException(503, "Semantic memory not initialized")
    entry = _semantic_mem.add(subject=subject, predicate=predicate, object=object, confidence=confidence)
    return SemanticEntryResponse(
        id=entry.id,
        subject=entry.subject,
        predicate=entry.predicate,
        object=entry.object,
        confidence=entry.confidence,
        access_count=entry.access_count,
        created_at=entry.created_at.isoformat(),
    )


@app.delete("/memory/semantic/{entry_id}")
async def delete_semantic(entry_id: str):
    if _semantic_mem is None:
        raise HTTPException(503, "Semantic memory not initialized")
    deleted = _semantic_mem.delete(entry_id)
    if not deleted:
        raise HTTPException(404, f"Entry {entry_id} not found")
    return {"deleted": entry_id}


## Procedural

@app.get("/memory/procedural", response_model=list[ProcedureResponse])
async def list_procedural():
    if _procedural_mem is None:
        raise HTTPException(503, "Procedural memory not initialized")
    return [
        ProcedureResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            steps=p.steps,
            use_count=p.use_count,
            success_rate=p.success_rate,
            tags=p.tags,
        )
        for p in _procedural_mem._procedures.values()
    ]


@app.post("/memory/procedural", response_model=ProcedureResponse)
async def add_procedure(name: str, description: str, steps: str, tags: str = ""):
    if _procedural_mem is None:
        raise HTTPException(503, "Procedural memory not initialized")
    step_list = [s.strip() for s in steps.split("\n") if s.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    proc = _procedural_mem.store(name=name, description=description, steps=step_list, tags=tag_list)
    return ProcedureResponse(
        id=proc.id,
        name=proc.name,
        description=proc.description,
        steps=proc.steps,
        use_count=proc.use_count,
        success_rate=proc.success_rate,
        tags=proc.tags,
    )


@app.get("/memory/procedural/search")
async def search_procedural(q: str = Query(...)):
    if _procedural_mem is None:
        raise HTTPException(503, "Procedural memory not initialized")
    results = _procedural_mem.find(q)
    return [
        ProcedureResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            steps=p.steps,
            use_count=p.use_count,
            success_rate=p.success_rate,
            tags=p.tags,
        )
        for p in results
    ]


# ─── Knowledge Graph ─────────────────────────────────────────────────────────

@app.get("/graph/entities")
async def list_entities():
    if _knowledge_graph is None:
        raise HTTPException(503, "Knowledge graph not initialized")
    return [
        {
            "id": e.id,
            "name": e.name,
            "type": e.entity_type.value,
            "properties": e.properties,
        }
        for e in _knowledge_graph._entities.values()
    ]


@app.post("/graph/entities", status_code=201)
async def create_entity(data: EntityCreate):
    if _knowledge_graph is None:
        raise HTTPException(503, "Knowledge graph not initialized")
    try:
        entity_type = EntityType(data.entity_type)
    except ValueError:
        raise HTTPException(400, f"Invalid entity_type: {data.entity_type}. Valid: {[e.value for e in EntityType]}")
    entity = _knowledge_graph.add_entity(name=data.name, entity_type=entity_type, properties=data.properties)
    return {"id": entity.id, "name": entity.name, "type": entity.entity_type.value}


@app.get("/graph/entities/{entity_id}")
async def get_entity(entity_id: str):
    if _knowledge_graph is None:
        raise HTTPException(503, "Knowledge graph not initialized")
    entity = _knowledge_graph.get_entity(entity_id)
    if not entity:
        raise HTTPException(404, f"Entity {entity_id} not found")
    rels = _knowledge_graph.get_relationships(entity_id)
    return {
        "id": entity.id,
        "name": entity.name,
        "type": entity.entity_type.value,
        "properties": entity.properties,
        "relationships": [
            {"id": r.id, "type": r.relationship_type.value, "confidence": r.confidence}
            for r in rels
        ],
    }


@app.post("/graph/relationships", status_code=201)
async def create_relationship(data: RelationshipCreate):
    if _knowledge_graph is None:
        raise HTTPException(503, "Knowledge graph not initialized")
    try:
        rel_type = RelationshipType(data.relationship_type)
    except ValueError:
        raise HTTPException(400, f"Invalid relationship_type. Valid: {[r.value for r in RelationshipType]}")

    # Find entities by name
    from_entities = [e for e in _knowledge_graph._entities.values() if e.name == data.from_entity_name]
    to_entities = [e for e in _knowledge_graph._entities.values() if e.name == data.to_entity_name]
    if not from_entities:
        raise HTTPException(404, f"Entity '{data.from_entity_name}' not found")
    if not to_entities:
        raise HTTPException(404, f"Entity '{data.to_entity_name}' not found")

    rel = _knowledge_graph.relate(from_entities[0], to_entities[0], rel_type, confidence=data.confidence)
    return {"id": rel.id, "type": rel.relationship_type.value, "confidence": rel.confidence}


@app.get("/graph/search")
async def graph_search(query: str, top_k: int = 5):
    if _knowledge_graph is None:
        raise HTTPException(503, "Knowledge graph not initialized")
    results = _knowledge_graph.semantic_search(query, top_k=top_k)
    return [
        {"id": e.id, "name": e.name, "type": e.entity_type.value, "score": float(score)}
        for e, score in results
    ]


# ─── Task Decomposition ──────────────────────────────────────────────────────

@app.post("/tasks/decompose")
async def decompose_task(goal: str, execute: bool = False):
    from riks_context_engine.tasks.decomposer import TaskDecomposer
    decomposer = TaskDecomposer()
    graph = decomposer.decompose(goal)
    if execute:
        completed: set[str] = set()
        ready = graph.get_ready_tasks(completed)
        for task in ready:
            task.mark_done()
            completed.add(task.id)
    return {
        "goal": graph.goal,
        "tasks": [
            TaskResponse(
                id=t.id,
                name=t.name,
                description=t.description,
                status=t.status.value,
                dependencies=t.dependencies,
            )
            for t in graph.tasks
        ],
    }


# ─── Reflection ──────────────────────────────────────────────────────────────

@app.post("/reflection/analyze", response_model=dict)
async def analyze_reflection(data: ReflectionAnalyzeRequest):
    from riks_context_engine.reflection.analyzer import ReflectionAnalyzer
    analyzer = ReflectionAnalyzer()
    report = analyzer.analyze(
        interaction_id=data.interaction_id,
        went_well=data.went_well,
        went_wrong=data.went_wrong,
        missing_info=data.missing_info,
    )
    return {
        "interaction_id": report.interaction_id,
        "went_well": report.went_well,
        "went_wrong": report.went_wrong,
        "missing_info": report.missing_info,
        "lessons": [
            LessonResponse(
                id=l.id,
                category=l.category,
                observation=l.observation,
                lesson_text=l.lesson_text,
                severity=l.severity,
                occurrence_count=l.occurrence_count,
                resolved=l.resolved,
            ).model_dump()
            for l in report.lessons
        ],
        "timestamp": report.timestamp.isoformat(),
    }


@app.get("/reflection/lessons", response_model=list[LessonResponse])
async def get_lessons(include_resolved: bool = False):
    from riks_context_engine.reflection.analyzer import ReflectionAnalyzer
    analyzer = ReflectionAnalyzer()
    lessons = analyzer.get_active_lessons()
    all_lessons = analyzer._lessons
    if not include_resolved:
        all_lessons = [l for l in all_lessons if not l.resolved]
    return [
        LessonResponse(
            id=l.id,
            category=l.category,
            observation=l.observation,
            lesson_text=l.lesson_text,
            severity=l.severity,
            occurrence_count=l.occurrence_count,
            resolved=l.resolved,
        )
        for l in all_lessons
    ]


# ─── CLI integration ────────────────────────────────────────────────────────

@app.post("/serve")
async def start_server(host: str = "0.0.0.0", port: int = 8000):
    """Start the uvicorn server (self-hosting)."""
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    # Run in background task - this endpoint doesn't return normally
    import asyncio
    asyncio.get_event_loop().create_task(server.serve())
    return {"status": "starting", "host": host, "port": port}
