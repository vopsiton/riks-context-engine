"""FastAPI server for Rik's Context Engine web UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# NOTE: Add `fastapi` and `uvicorn` to pyproject.toml dependencies if not present.


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str | None = None


_MODELS = ["gemma4-31b-it", "qwen3.5-9b", "gemma-4-31b", "minimax-m2.7"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


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

    # TODO: Wire up actual context engine + memory + LLM call here.
    return ChatResponse(
        response=f"[{model}] Mesajını aldım: {req.message!r} — "
        "Context engine entegrasyonu yakında aktif olacak.",
        model=model,
    )


@app.get("/")
def root() -> FileResponse:
    ui_path = os.environ.get("UI_PATH", "ui/index.html")
    return FileResponse(ui_path)
