"""FastAPI server for Rik's Context Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from riks_context_engine.context.manager import ContextWindowManager, ContextMessage
from riks_context_engine.memory.episodic import EpisodicMemory, EpisodicEntry
from riks_context_engine.memory.semantic import SemanticMemory, SemanticEntry
from riks_context_engine.memory.procedural import ProceduralMemory, Procedure
from riks_context_engine.graph.knowledge_graph import (
    KnowledgeGraph,
    Entity,
    Relationship,
    EntityType,
    RelationshipType,
)
from riks_context_engine.tasks.decomposer import TaskDecomposer, TaskGraph, Task, TaskStatus
from riks_context_engine.reflection.analyzer import ReflectionAnalyzer, ReflectionReport, Lesson

# ─── Pydantic request/response models ─────────────────────────────────────────

class MessageAddRequest(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    is_grounding: bool = False
    priority_tier: int = Field(default=2, ge=0, le=3)

class MessageAddResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    importance: float
    tokens: int
    is_grounding: bool
    priority_tier: int

class ContextStatsResponse(BaseModel):
    current_tokens: int
    max_tokens: int
    messages_count: int
    active_messages_count: int
    pruning_count: int
    last_prune_timestamp: Optional[str]
    tokens_remaining: int
    needs_pruning: bool

class EpisodicAddRequest(BaseModel):
    content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: Optional[list[str]] = None

class SemanticAddRequest(BaseModel):
    subject: str
    predicate: str
    object: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

class ProcedureStoreRequest(BaseModel):
    name: str
    description: str
    steps: list[str]

class EntityAddRequest(BaseModel):
    name: str
    entity_type: str
    properties: Optional[dict] = None

class RelationCreateRequest(BaseModel):
    from_entity_id: str
    to_entity_id: str
    relationship_type: str
    confidence: float = 1.0

class GoalDecomposeRequest(BaseModel):
    goal: str
    execute: bool = False

class ReflectionAnalyzeRequest(BaseModel):
    interaction_id: str
    conversation: list[dict]


# ─── Engine wrapper (holds all subsystems) ─────────────────────────────────────

class ContextEngine:
    """In-memory context engine combining all subsystems."""

    def __init__(self):
        self.context = ContextWindowManager(max_tokens=50_000)
        self.episodic = EpisodicMemory(storage_path=":memory:")
        self.semantic = SemanticMemory(db_path=":memory:")
        self.procedural = ProceduralMemory(storage_path=":memory:")
        self.graph = KnowledgeGraph(db_path=":memory:")
        self.decomposer = TaskDecomposer()
        self.reflection = ReflectionAnalyzer(semantic_memory=None)


# ─── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Rik's Context Engine API", version="0.1.0")

# Module-level engine instance
_engine: ContextEngine | None = None

def get_engine() -> ContextEngine:
    global _engine
    if _engine is None:
        _engine = ContextEngine()
    return _engine


# ─── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ─── Context Window ─────────────────────────────────────────────────────────────

@app.post("/api/context/messages", response_model=MessageAddResponse)
def context_add_message(body: MessageAddRequest, engine: ContextEngine = Depends(get_engine)):
    msg = engine.context.add(
        role=body.role,
        content=body.content,
        importance=body.importance,
        is_grounding=body.is_grounding,
        priority_tier=body.priority_tier,
    )
    return MessageAddResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        timestamp=msg.timestamp.isoformat(),
        importance=msg.importance,
        tokens=msg.tokens,
        is_grounding=msg.is_grounding,
        priority_tier=msg.priority_tier,
    )

@app.get("/api/context/messages", response_model=list[MessageAddResponse])
def context_get_messages(include_pruned: bool = False, engine: ContextEngine = Depends(get_engine)):
    messages = engine.context.get_messages(include_pruned=include_pruned)
    return [
        MessageAddResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            timestamp=m.timestamp.isoformat(),
            importance=m.importance,
            tokens=m.tokens,
            is_grounding=m.is_grounding,
            priority_tier=m.priority_tier,
        )
        for m in messages
    ]

@app.get("/api/context/stats", response_model=ContextStatsResponse)
def context_stats(engine: ContextEngine = Depends(get_engine)):
    s = engine.context.stats
    return ContextStatsResponse(
        current_tokens=s.current_tokens,
        max_tokens=s.max_tokens,
        messages_count=s.messages_count,
        active_messages_count=s.active_messages_count,
        pruning_count=s.pruning_count,
        last_prune_timestamp=s.last_prune_timestamp.isoformat() if s.last_prune_timestamp else None,
        tokens_remaining=engine.context.tokens_remaining(),
        needs_pruning=engine.context.needs_pruning(),
    )

@app.post("/api/context/prune")
def context_prune(engine: ContextEngine = Depends(get_engine)):
    before = engine.context.stats.current_tokens
    engine.context._prune_if_needed()
    return {
        "pruned": True,
        "tokens_before": before,
        "tokens_after": engine.context.stats.current_tokens,
    }

@app.post("/api/context/reset")
def context_reset(engine: ContextEngine = Depends(get_engine)):
    engine.context.reset()
    return {"reset": True}


# ─── Episodic Memory ───────────────────────────────────────────────────────────

@app.post("/api/memory/episodic", status_code=201)
def episodic_add(body: EpisodicAddRequest, engine: ContextEngine = Depends(get_engine)):
    entry = engine.episodic.add(content=body.content, importance=body.importance, tags=body.tags)
    return {
        "id": entry.id,
        "content": entry.content,
        "importance": entry.importance,
        "tags": entry.tags,
        "timestamp": entry.timestamp.isoformat(),
    }

@app.get("/api/memory/episodic/{entry_id}")
def episodic_get(entry_id: str, engine: ContextEngine = Depends(get_engine)):
    entry = engine.episodic.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Episodic entry not found")
    return {
        "id": entry.id,
        "content": entry.content,
        "importance": entry.importance,
        "tags": entry.tags,
        "timestamp": entry.timestamp.isoformat(),
    }

@app.delete("/api/memory/episodic/{entry_id}")
def episodic_delete(entry_id: str, engine: ContextEngine = Depends(get_engine)):
    if not engine.episodic.delete(entry_id):
        raise HTTPException(status_code=404, detail="Episodic entry not found")
    return {"deleted": True}

@app.get("/api/memory/episodic", response_model=list[dict])
def episodic_query(q: str = Query(..., alias="query"), limit: int = 10, engine: ContextEngine = Depends(get_engine)):
    entries = engine.episodic.query(query=q, limit=limit)
    return [
        {
            "id": e.id,
            "content": e.content,
            "importance": e.importance,
            "tags": e.tags,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in entries
    ]


# ─── Semantic Memory ───────────────────────────────────────────────────────────

@app.post("/api/memory/semantic", status_code=201)
def semantic_add(body: SemanticAddRequest, engine: ContextEngine = Depends(get_engine)):
    entry = engine.semantic.add(
        subject=body.subject,
        predicate=body.predicate,
        object=body.object,
        confidence=body.confidence,
    )
    return {
        "id": entry.id,
        "subject": entry.subject,
        "predicate": entry.predicate,
        "object": entry.object,
        "confidence": entry.confidence,
        "created_at": entry.created_at.isoformat(),
        "last_accessed": entry.last_accessed.isoformat(),
        "access_count": entry.access_count,
    }

@app.get("/api/memory/semantic/{entry_id}")
def semantic_get(entry_id: str, engine: ContextEngine = Depends(get_engine)):
    entry = engine.semantic.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Semantic entry not found")
    return {
        "id": entry.id,
        "subject": entry.subject,
        "predicate": entry.predicate,
        "object": entry.object,
        "confidence": entry.confidence,
        "created_at": entry.created_at.isoformat(),
        "last_accessed": entry.last_accessed.isoformat(),
        "access_count": entry.access_count,
    }

@app.delete("/api/memory/semantic/{entry_id}")
def semantic_delete(entry_id: str, engine: ContextEngine = Depends(get_engine)):
    if not engine.semantic.delete(entry_id):
        raise HTTPException(status_code=404, detail="Semantic entry not found")
    return {"deleted": True}

@app.get("/api/memory/semantic", response_model=list[dict])
def semantic_query(
    subject: Optional[str] = None,
    predicate: Optional[str] = None,
    recall: Optional[str] = None,
    engine: ContextEngine = Depends(get_engine),
):
    if recall:
        entries = engine.semantic.recall(recall)
    else:
        entries = engine.semantic.query(subject=subject, predicate=predicate)
    return [
        {
            "id": e.id,
            "subject": e.subject,
            "predicate": e.predicate,
            "object": e.object,
            "confidence": e.confidence,
            "created_at": e.created_at.isoformat(),
            "last_accessed": e.last_accessed.isoformat(),
            "access_count": e.access_count,
        }
        for e in entries
    ]


# ─── Procedural Memory ─────────────────────────────────────────────────────────

@app.post("/api/memory/procedural", status_code=201)
def procedural_store(body: ProcedureStoreRequest, engine: ContextEngine = Depends(get_engine)):
    proc = engine.procedural.store(name=body.name, description=body.description, steps=body.steps)
    return {
        "id": proc.id,
        "name": proc.name,
        "description": proc.description,
        "steps": proc.steps,
        "created_at": proc.created_at.isoformat(),
        "last_used": proc.last_used.isoformat(),
        "use_count": proc.use_count,
        "success_rate": proc.success_rate,
    }

@app.get("/api/memory/procedural/{proc_id}")
def procedural_get(proc_id: str, engine: ContextEngine = Depends(get_engine)):
    proc = engine.procedural.get(proc_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return {
        "id": proc.id,
        "name": proc.name,
        "description": proc.description,
        "steps": proc.steps,
        "created_at": proc.created_at.isoformat(),
        "last_used": proc.last_used.isoformat(),
        "use_count": proc.use_count,
        "success_rate": proc.success_rate,
    }

@app.delete("/api/memory/procedural/{proc_id}")
def procedural_delete(proc_id: str, engine: ContextEngine = Depends(get_engine)):
    proc = engine.procedural.get(proc_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return {"deleted": True}

@app.get("/api/memory/procedural", response_model=list[dict])
def procedural_find(q: str = Query(..., alias="query"), engine: ContextEngine = Depends(get_engine)):
    procs = engine.procedural.find(query=q)
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "steps": p.steps,
            "created_at": p.created_at.isoformat(),
            "last_used": p.last_used.isoformat(),
            "use_count": p.use_count,
            "success_rate": p.success_rate,
        }
        for p in procs
    ]


# ─── Knowledge Graph ────────────────────────────────────────────────────────────

@app.post("/api/graph/entities", status_code=201)
def graph_add_entity(body: EntityAddRequest, engine: ContextEngine = Depends(get_engine)):
    try:
        entity_type = EntityType(body.entity_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid entity_type: {body.entity_type}")
    entity = engine.graph.add_entity(name=body.name, entity_type=entity_type, properties=body.properties)
    return {
        "id": entity.id,
        "name": entity.name,
        "entity_type": entity.entity_type.value,
        "properties": entity.properties,
        "created_at": entity.created_at.isoformat(),
        "last_updated": entity.last_updated.isoformat(),
    }

@app.get("/api/graph/entities/{entity_id}")
def graph_get_entity(entity_id: str, engine: ContextEngine = Depends(get_engine)):
    entity = engine.graph.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {
        "id": entity.id,
        "name": entity.name,
        "entity_type": entity.entity_type.value,
        "properties": entity.properties,
        "created_at": entity.created_at.isoformat(),
        "last_updated": entity.last_updated.isoformat(),
    }

@app.post("/api/graph/relations", status_code=201)
def graph_relate(body: RelationCreateRequest, engine: ContextEngine = Depends(get_engine)):
    try:
        rel_type = RelationshipType(body.relationship_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid relationship_type: {body.relationship_type}")

    from_entity = engine.graph.get_entity(body.from_entity_id)
    to_entity = engine.graph.get_entity(body.to_entity_id)
    if not from_entity:
        raise HTTPException(status_code=404, detail=f"From entity not found: {body.from_entity_id}")
    if not to_entity:
        raise HTTPException(status_code=404, detail=f"To entity not found: {body.to_entity_id}")

    rel = engine.graph.relate(from_entity, to_entity, rel_type, confidence=body.confidence)
    return {
        "id": rel.id,
        "from_entity_id": rel.from_entity_id,
        "to_entity_id": rel.to_entity_id,
        "relationship_type": rel.relationship_type.value,
        "confidence": rel.confidence,
        "created_at": rel.created_at.isoformat(),
    }

@app.get("/api/graph/entities/{entity_id}/relationships")
def graph_entity_rels(entity_id: str, engine: ContextEngine = Depends(get_engine)):
    rels = engine.graph.get_relationships(entity_id)
    return [
        {
            "id": r.id,
            "from_entity_id": r.from_entity_id,
            "to_entity_id": r.to_entity_id,
            "relationship_type": r.relationship_type.value,
            "confidence": r.confidence,
        }
        for r in rels
    ]

@app.get("/api/graph/query")
def graph_query(
    entity_name: Optional[str] = None,
    relationship_type: Optional[str] = None,
    engine: ContextEngine = Depends(get_engine),
):
    rel_type = RelationshipType(relationship_type) if relationship_type else None
    results = engine.graph.query(entity_name=entity_name, relationship_type=rel_type)
    out = []
    for r in results:
        if isinstance(r, Entity):
            out.append({
                "type": "entity",
                "id": r.id,
                "name": r.name,
                "entity_type": r.entity_type.value,
                "properties": r.properties,
            })
        else:
            out.append({
                "type": "relationship",
                "id": r.id,
                "from_entity_id": r.from_entity_id,
                "to_entity_id": r.to_entity_id,
                "relationship_type": r.relationship_type.value,
                "confidence": r.confidence,
            })
    return out


# ─── Task Decomposition ────────────────────────────────────────────────────────

@app.post("/api/tasks/decompose")
def tasks_decompose(body: GoalDecomposeRequest, engine: ContextEngine = Depends(get_engine)):
    graph = engine.decomposer.decompose(goal=body.goal)
    if body.execute:
        graph = engine.decomposer.execute(graph)
    valid, err = engine.decomposer.validate_graph(graph)
    return {
        "goal": graph.goal,
        "tasks": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "status": t.status.value,
                "dependencies": t.dependencies,
                "parallel_group": t.parallel_group,
                "success_criteria": t.success_criteria,
                "retry_count": t.retry_count,
                "created_at": t.created_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in graph.tasks
        ],
        "valid": valid,
        "validation_error": err,
    }

@app.get("/api/tasks/{task_id}")
def tasks_get(task_id: str, engine: ContextEngine = Depends(get_engine)):
    raise HTTPException(status_code=404, detail="Task not found")


# ─── Self-Reflection ───────────────────────────────────────────────────────────

@app.post("/api/reflection/analyze")
def reflection_analyze(body: ReflectionAnalyzeRequest, engine: ContextEngine = Depends(get_engine)):
    report = engine.reflection.analyze(
        interaction_id=body.interaction_id,
        conversation=body.conversation,
    )
    return {
        "interaction_id": report.interaction_id,
        "went_well": report.went_well,
        "went_wrong": report.went_wrong,
        "missing_info": report.missing_info,
        "lessons": [
            {
                "id": l.id,
                "category": l.category,
                "observation": l.observation,
                "lesson_text": l.lesson_text,
                "severity": l.severity,
                "occurrence_count": l.occurrence_count,
                "resolved": l.resolved,
            }
            for l in report.lessons
        ],
        "timestamp": report.timestamp.isoformat(),
    }

@app.get("/api/reflection/lessons")
def reflection_lessons(engine: ContextEngine = Depends(get_engine)):
    lessons = engine.reflection.get_active_lessons()
    return [
        {
            "id": l.id,
            "category": l.category,
            "observation": l.observation,
            "lesson_text": l.lesson_text,
            "severity": l.severity,
            "occurrence_count": l.occurrence_count,
            "resolved": l.resolved,
        }
        for l in lessons
    ]

@app.post("/api/reflection/resolve/{lesson_id}")
def reflection_resolve(lesson_id: str, engine: ContextEngine = Depends(get_engine)):
    resolved = engine.reflection.resolve_lesson(lesson_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {"resolved": True}

@app.get("/api/reflection/mistakes")
def reflection_mistakes(engine: ContextEngine = Depends(get_engine)):
    return engine.reflection.track_mistake_frequency()