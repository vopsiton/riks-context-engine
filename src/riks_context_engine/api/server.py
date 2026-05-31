"""FastAPI server for Rik's Context Engine web UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.export import (
    dump_manifest,
    export_memory,
    import_to_memory,
    parse_manifest,
)
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str | None = None


_MODELS = ["gemma4-31b-it", "qwen3.5-9b", "gemma-4-31b", "minimax-m2.7"]

# Module-level memory instances (set on startup via lifespan)
_episodic_memory: EpisodicMemory | None = None
_semantic_memory: SemanticMemory | None = None
_procedural_memory: ProceduralMemory | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _episodic_memory, _semantic_memory, _procedural_memory
    data_dir = os.environ.get("DATA_DIR", "data")
    _episodic_memory = EpisodicMemory(storage_path=f"{data_dir}/episodic.json")
    _semantic_memory = SemanticMemory(db_path=f"{data_dir}/semantic.db")
    _procedural_memory = ProceduralMemory(storage_path=f"{data_dir}/procedural.json")
    yield
    _episodic_memory = _semantic_memory = _procedural_memory = None


app = FastAPI(
    title="Rik's Context Engine API",
    description="HTTP API for AI context and memory management",
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models")
def list_models() -> dict[str, list[str]]:
    return {"models": _MODELS}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    model = req.model or "gemma4-31b-it"
    if model not in _MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")

    return ChatResponse(
        response=f"[{model}] Mesajını aldım: {req.message!r} — "
        "Context engine entegrasyonu yakında aktif olacak.",
        model=model,
    )


@app.get("/")
def root() -> FileResponse:
    ui_path = os.environ.get("UI_PATH", "ui/index.html")
    return FileResponse(ui_path)


# ─── Memory Export/Import Endpoints ───────────────────────────────────────────


class MemoryExportResponse(BaseModel):
    export_id: str
    schema_version: str
    counts: dict[str, int]
    data: str


class MemoryImportRequest(BaseModel):
    content: str = Field(..., description="JSON or YAML manifest content")
    format: Literal["json", "yaml"] = "json"
    merge: bool = Field(True, description="If true, skip duplicate IDs; if false, replace all")


class MemoryImportResponse(BaseModel):
    imported: dict[str, int]
    schema_version: str


@app.get("/api/v1/memory/export", response_model=MemoryExportResponse)
def export_memory_api(
    types: Annotated[
        str | None,
        Query(description="Comma-separated types: episodic,semantic,procedural"),
    ] = None,
    format: Annotated[
        Literal["json", "yaml"] | None,
        Query(description="Output format"),
    ] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    tags: Annotated[
        str | None,
        Query(description="Comma-separated tags filter"),
    ] = None,
) -> MemoryExportResponse:
    """Export memory tiers as JSON or YAML."""
    if format is None:
        format = "json"

    include_types = [t.strip() for t in types.split(",")] if types else None
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    manifest = export_memory(
        episodic_memory=_episodic_memory,
        semantic_memory=_semantic_memory,
        procedural_memory=_procedural_memory,
        include_types=include_types,
        date_from=date_from,
        date_to=date_to,
        tags=tag_list,
    )

    serialized = dump_manifest(manifest, format)
    counts = {
        "episodic": len(manifest.episodic),
        "semantic": len(manifest.semantic),
        "procedural": len(manifest.procedural),
    }

    return MemoryExportResponse(
        export_id=manifest.metadata.export_id,
        schema_version=manifest.metadata.schema_version,
        counts=counts,
        data=serialized,
    )


@app.post("/api/v1/memory/import", response_model=MemoryImportResponse)
def import_memory_api(req: MemoryImportRequest) -> MemoryImportResponse:
    """Import memory tiers from a JSON or YAML manifest."""
    try:
        manifest = parse_manifest(req.content, req.format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    imported = import_to_memory(
        manifest,
        episodic_memory=_episodic_memory,
        semantic_memory=_semantic_memory,
        procedural_memory=_procedural_memory,
        merge=req.merge,
    )

    return MemoryImportResponse(
        imported=imported,
        schema_version=manifest.metadata.schema_version,
    )
