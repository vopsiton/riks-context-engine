"""FastAPI server for Rik's Context Engine web UI."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Lock
from typing import Annotated, Any, Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.export import (
    dump_manifest,
    export_memory,
    import_to_memory,
    parse_manifest,
)
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory

import httpx


# ─── LLM Client (Ollama) ──────────────────────────────────────────────────────────
_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# Model name mapping: UI name → Ollama name
_OLLAMA_MODEL_MAP = {
    "gemma4-31b-it": "gemma4-31b:latest",
    "qwen3.5-9b": "qwen3.5-9b:latest",
    "gemma-4-31b": "gemma4-31b:latest",
    "minimax-m2.7": "qwen3.5-9b:latest",  # fallback
}


def _ollama_chat(model_ui_name: str, message: str) -> str:
    """Call Ollama chat API and return the response text."""
    ollama_model = _OLLAMA_MODEL_MAP.get(model_ui_name, "qwen3.5-9b:latest")
    
    payload = {
        "model": ollama_model,
        "messages": [
            {"role": "user", "content": message}
        ],
        "stream": False,
    }
    
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{_OLLAMA_URL}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "")
    except Exception as e:
        return f"[HATA] Ollama baglantisi basarisiz: {e}"


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str | None = None


_MODELS = ["gemma4-31b-it", "qwen3.5-9b", "gemma-4-31b", "minimax-m2.7"]

# ─── Rate Limiting ─────────────────────────────────────────────────────────────
_RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "100"))
_RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # seconds

# Per-IP request tracking: {ip: [(timestamp, count)]}
_ip_request_log: dict[str, list[tuple[float, int]]] = defaultdict(list)
_ip_lock = Lock()



def _get_client_ip(request: Request) -> str:
    """"Extract client IP, checking X-Forwarded-For first."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> tuple[bool, int, int]:
    """Check if IP is within rate limit.


    Returns (allowed, remaining, reset_seconds).
    """
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW

    with _ip_lock:
        # Prune old entries
        _ip_request_log[ip] = [
            (ts, cnt) for ts, cnt in _ip_request_log[ip] if ts > window_start
        ]
        entries = _ip_request_log[ip]

        total = sum(cnt for _, cnt in entries)
        remaining = max(0, _RATE_LIMIT_REQUESTS - total)

        if remaining == 0:
            oldest = min(ts for ts, _ in entries) if entries else now
            reset_seconds = int(oldest + _RATE_LIMIT_WINDOW - now)
            return False, 0, max(1, reset_seconds)

        return True, remaining - 1, _RATE_LIMIT_WINDOW


def _record_request(ip: str) -> None:
    """Record a request for rate limiting."""
    now = time.time()
    with _ip_lock:
        _ip_request_log[ip].append((now, 1))



class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for per-IP rate limiting."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Skip rate limiting for health endpoint
        if request.url.path == "/health":
            return await call_next(request)  # type: ignore[no-any-return]

        ip = _get_client_ip(request)
        allowed, remaining, reset = _check_rate_limit(ip)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests"},
                headers={
                    "X-RateLimit-Limit": str(_RATE_LIMIT_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                    "Retry-After": str(reset),
                },
            )


        _record_request(ip)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)
        return response  # type: ignore[no-any-return]


# Module-level memory instances (set on startup via lifespan)
_episodic_memory: EpisodicMemory | None = None
_semantic_memory: SemanticMemory | None = None
_procedural_memory: ProceduralMemory | None = None


def _get_allowed_origins() -> list[str]:
    """Parse ALLOWED_ORIGINS env var into a list of origins."""
    origins_env = os.environ.get("ALLOWED_ORIGINS", "")
    if not origins_env:
        return ["http://localhost:3000", "http://localhost:8080"]
    return [o.strip() for o in origins_env.split(",") if o.strip()]


def _build_cors_config() -> dict[str, list[str] | bool]:
    """Build CORS middleware configuration from environment."""
    origins = _get_allowed_origins()
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
        "allow_headers": ["Authorization", "Content-Type", "X-Request-ID"],
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
    **cast(dict[str, Any], _build_cors_config()),
)

app.add_middleware(RateLimitMiddleware)



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

    # Call Ollama for real AI response
    response_text = _ollama_chat(model, req.message)

    return ChatResponse(
        response=response_text,
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
