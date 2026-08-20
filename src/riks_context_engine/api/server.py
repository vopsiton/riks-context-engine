"""FastAPI server for Rik's Context Engine web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from riks_context_engine.api.audit_log import (
    CRITICAL_MEMORY_IMPORT,
    get_audit_log,
    is_admin_api_key,
    record_request,
)
from riks_context_engine.api.audit_log import _default_tenant as _audit_default_tenant
from riks_context_engine.api.telemetry import (
    get_prometheus_output,
    observe_request,
    setup_telemetry,
)
from riks_context_engine.chat_context import (
    build_context_block,
    build_llm_prompt,
    remember_exchange,
)
from riks_context_engine.context.manager import ContextWindowManager
from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.export import (
    dump_manifest,
    export_memory,
    import_to_memory,
    parse_manifest,
)
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory
from riks_context_engine.multi_tenant import (
    TENANT_HEADER,
    TenantContextRegistry,
    TenantMemoryRegistry,
    TenantValidationError,
    validate_tenant_id,
)


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str | None = None


_MODELS = ["gemma4-31b-it", "gemma4:31b", "qwen3.5-9b", "gemma-4-31b", "minimax-m2.7"]

API_KEY = os.environ.get("API_KEY", "")


def _default_llm_call(prompt: str, model: str) -> str:
    """Default LLM provider call.

    If a provider URL is configured (LLM_PROVIDER_URL env var), call it.
    Otherwise, use the deterministic stub (proves the wiring in CI/staging
    without a real LLM). The stub reads the context block and answers name
    questions from it.
    """
    provider_url = os.environ.get("LLM_PROVIDER_URL", "")
    if provider_url:
        # Real LLM provider (e.g., Ollama, OpenAI-compatible).
        # POST to the provider's chat/completion endpoint.
        import urllib.request

        # Try Ollama format first (/api/chat), then OpenAI-compatible.
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        req = urllib.request.Request(
            provider_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                # Ollama: {"message": {"content": "..."}}
                # OpenAI: {"choices": [{"message": {"content": "..."}}]}
                if "message" in data:
                    return str(data["message"].get("content", ""))
                if "choices" in data:
                    return str(data["choices"][0]["message"]["content"])
                return str(data)
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM provider call failed: %s", e)
            # Fall through to the stub (provider unreachable → stub).

    # Deterministic stub (CI/testing/no-provider).
    # The user message is embedded in the prompt as "User message: <text>".
    import re

    from riks_context_engine.chat_context import _stub_llm

    m = re.search(r"User message: (.+)", prompt)
    user_message = m.group(1) if m else ""
    return _stub_llm(prompt, model, user_message)


# ─── API Key Middleware ────────────────────────────────────────────────────────

_API_KEY_PROTECTED_PATHS = frozenset(
    [
        "/",
        "/api/chat",
        "/api/v1/memory/export",
        "/api/v1/memory/import",
        "/models",
        "/api/v1/context/messages",
        "/api/v1/context/summary",
        "/api/v1/audit",
        "/api/v1/audit/operation",
    ]
)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for API key authentication (#110).

    - When an ``API_KEY`` is configured, every protected path requires a
      matching ``X-API-Key`` header; missing/mismatched -> ``401``.
    - When no ``API_KEY`` is configured, protected paths are open (local
      dev) — preserved from prior behavior so existing dev/CI flows do not
      break (no breaking change, #110).
    - Stores the presented key on ``request.state.api_key`` so the audit
      middleware can derive the caller's role.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        api_key = request.headers.get("X-API-Key")
        request.state.api_key = api_key
        if path in _API_KEY_PROTECTED_PATHS and API_KEY:
            if api_key != API_KEY:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)


# ─── Tenant Isolation (closes part of #102) ──────────────────────────────────


class TenantAuthMiddleware(BaseHTTPMiddleware):
    """Validate the X-Tenant-Id header on protected paths (#102).

    Consistent contract (all tenant-validation failures -> 401):
    - header missing -> 401
    - header empty/whitespace -> 401
    - header malformed (bad chars / >64 chars) -> 401

    The validated id is stored on ``request.state.tenant_id`` for
    downstream handlers.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _API_KEY_PROTECTED_PATHS:
            try:
                request.state.tenant_id = validate_tenant_id(request.headers.get(TENANT_HEADER))
            except TenantValidationError as exc:
                return JSONResponse(status_code=401, content={"detail": exc.detail})
        return await call_next(request)


# ─── Audit Logging (#110) ───────────────────────────────────────────────────


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Record every HTTP request in the tenant-scoped audit log (#110).

    Captures timestamp, tenant, endpoint, method, status code, latency and
    the caller's role (derived from the API key). Runs *last* (innermost) so
    it measures the time the downstream handlers actually took, and records
    the final status code (including 401s raised by auth/tenant middleware
    for protected paths). Requests with no validated tenant are attributed
    to the ``RIKS_TENANT_ID`` env default or ``unauthenticated``.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000.0
        tenant = getattr(request.state, "tenant_id", None) or _audit_default_tenant()
        record_request(
            tenant=tenant,
            endpoint=request.url.path,
            method=request.method,
            status=response.status_code,
            latency_ms=latency_ms,
            api_key=getattr(request.state, "api_key", None),
        )
        # Prometheus metrics (#103): every request feeds request_count, the
        # latency histogram, and error_count (status >= 500). Global (no
        # tenant split) — Prometheus standard.
        observe_request(latency_ms / 1000.0, response.status_code)
        return response


# ─── Rate Limiting (#99) ──────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class RateLimitConfig:
    """Sliding-window rate limit settings.

    Config schema (env vars, loaded at import time):

    - ``RATE_LIMIT_ENABLED`` (bool, default ``false``) — master switch.
    - ``RATE_LIMIT_MODE`` (``"ip"`` | ``"user"``, default ``"ip"``) — key
      requests by client IP or by ``X-Tenant-Id`` / API-key identity.
    - ``RATE_LIMIT_REQUESTS`` (int, default ``100``) — ``max_requests``.
    - ``RATE_LIMIT_WINDOW`` (int seconds, default ``60``) — ``window_seconds``.
    """

    def __init__(self) -> None:
        self.enabled: bool = _env_bool("RATE_LIMIT_ENABLED", False)
        self.mode: str = os.environ.get("RATE_LIMIT_MODE", "ip").strip().lower()
        if self.mode not in {"ip", "user"}:
            self.mode = "ip"
        self.max_requests: int = int(os.environ.get("RATE_LIMIT_REQUESTS", "100"))
        self.window_seconds: int = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))


_RATE_LIMIT_REQUESTS = 100  # kept for backwards compatibility
_RATE_LIMIT_WINDOW = 60  # kept for backwards compatibility

# Sliding-window request tracking: {key: [timestamps within window]}
_rate_limit_log: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = Lock()


def _get_client_ip(request: Request) -> str:
    """Extract client IP, checking X-Forwarded-For first."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request, mode: str) -> str:
    """Build the rate-limit key for a request (per-IP or per-user)."""
    if mode == "user":
        tenant = request.headers.get(TENANT_HEADER, "").strip()
        if tenant:
            return f"user:{tenant}"
    return f"ip:{_get_client_ip(request)}"


def _check_rate_limit(
    ip: str, *, max_requests: int = _RATE_LIMIT_REQUESTS, window: int = _RATE_LIMIT_WINDOW
) -> tuple[bool, int, int]:
    """Check a sliding window for ``ip`` without recording the request.

    Returns (allowed, remaining, reset_seconds).
    """
    now = time.time()
    window_start = now - window

    with _rate_limit_lock:
        entries = [ts for ts in _rate_limit_log[ip] if ts > window_start]
        _rate_limit_log[ip] = entries

        total = len(entries)
        remaining = max(0, max_requests - total)

        if remaining == 0:
            oldest = min(entries) if entries else now
            reset_seconds = oldest + window - now
            return False, 0, max(1, int(reset_seconds) or 1)

        return True, remaining - 1, window


def _record_request(ip: str) -> None:
    """Record a request for rate limiting."""
    now = time.time()
    with _rate_limit_lock:
        _rate_limit_log[ip].append(now)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for sliding-window rate limiting.

    Enabled only when ``RATE_LIMIT_ENABLED`` is truthy. On limit overflow the
    response is ``429`` with ``Retry-After``; on allowed responses the
    ``X-RateLimit-Limit`` / ``X-RateLimit-Remaining`` headers are set.
    """

    def __init__(self, app: Any, config: RateLimitConfig | None = None) -> None:
        super().__init__(app)
        self._config = config or RateLimitConfig()

    async def dispatch(self, request: Request, call_next):
        cfg = self._config
        if not cfg.enabled:
            return await call_next(request)

        # Skip rate limiting for health endpoint
        if request.url.path == "/health":
            return await call_next(request)

        key = _rate_limit_key(request, cfg.mode)
        allowed, remaining, reset = _check_rate_limit(
            key, max_requests=cfg.max_requests, window=cfg.window_seconds
        )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests"},
                headers={
                    "X-RateLimit-Limit": str(cfg.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                    "Retry-After": str(reset),
                },
            )

        _record_request(key)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(cfg.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# Module-level memory instances (set on startup via lifespan)
_episodic_memory: EpisodicMemory | None = None
_semantic_memory: SemanticMemory | None = None
_procedural_memory: ProceduralMemory | None = None

# Module-level context window manager for WebSocket streaming
_context_manager: ContextWindowManager | None = None


def _set_context_manager(mgr: ContextWindowManager | None) -> None:
    """Set the module-level context manager (called by lifespan)."""
    global _context_manager
    _context_manager = mgr


def _get_context_manager() -> ContextWindowManager | None:  # noqa: F821
    """Get the module-level context manager."""
    return _context_manager


# Module-level tenant-scoped context registry (#102)
_tenant_registry = TenantContextRegistry()

# Module-level tenant-scoped memory registry (#158: chat context wiring)
# Each tenant gets its own SemanticMemory instance, backed by tenant-scoped
# file paths under DATA_DIR.
_tenant_memory_registry = TenantMemoryRegistry()


# ─── WebSocket Context Streaming ───────────────────────────────────────────────

logger = logging.getLogger(__name__)

_WS_HEARTBEAT_INTERVAL = 30  # seconds
_WS_SUBSCRIBE_TIMEOUT = 5.0  # seconds to wait for subscription ack


class WSClientMessage(BaseModel):
    """Incoming message types from WebSocket client."""

    type: Literal["subscribe", "unsubscribe", "ping"]
    session_id: str | None = None
    include_stats: bool = True


class WSContextUpdate(BaseModel):
    """Context update pushed to WebSocket clients."""

    type: Literal[
        "context_update",
        "stats_update",
        "pruning_event",
        "heartbeat",
        "error",
        "subscribed",
        "unsubscribed",
    ]
    session_id: str | None = None
    messages: list[dict[str, Any]] = []
    stats: dict[str, Any] | None = None
    pruned_count: int = 0
    detail: str | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


class WebSocketContextStreamer:
    """Manages WebSocket client connections for context streaming.

    Clients connect to /ws/v1/context/stream and subscribe to receive
    real-time context window updates. Multiple clients can be subscribed
    simultaneously.

    Usage:
        >>> streamer = WebSocketContextStreamer()
        >>> await streamer.connect(websocket)
        >>> # broadcast a context update
        >>> await streamer.broadcast_context_update()
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}  # client_id -> WebSocket
        self._subscriptions: dict[str, str] = {}  # client_id -> session_id
        self._lock = asyncio.Lock()
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def client_count(self) -> int:
        """Number of connected WebSocket clients."""
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection

        Returns:
            Unique client_id for this connection
        """
        await websocket.accept()
        client_id = str(uuid.uuid4())[:8]
        async with self._lock:
            self._connections[client_id] = websocket
            self._subscriptions[client_id] = ""
        logger.debug(f"WebSocket client connected: {client_id} (total: {self.client_count})")
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Remove a client connection.

        Args:
            client_id: Client identifier
        """
        async with self._lock:
            self._connections.pop(client_id, None)
            self._subscriptions.pop(client_id, None)
            task = self._heartbeat_tasks.pop(client_id, None)
            if task and not task.done():
                task.cancel()
        logger.debug(f"WebSocket client disconnected: {client_id} (total: {self.client_count})")

    async def subscribe(self, client_id: str, session_id: str) -> None:
        """Subscribe a client to context updates for a session.

        Args:
            client_id: Client identifier
            session_id: Session to subscribe to (empty = all sessions)
        """
        async with self._lock:
            self._subscriptions[client_id] = session_id
        await self._send(
            client_id,
            WSContextUpdate(
                type="subscribed",
                session_id=session_id,
                detail=f"Subscribed to context updates for session: {session_id or 'all'}",
            ),
        )
        logger.debug(f"Client {client_id} subscribed to session: {session_id or 'all'}")

    async def unsubscribe(self, client_id: str) -> None:
        """Unsubscribe a client from context updates.

        Args:
            client_id: Client identifier
        """
        async with self._lock:
            self._subscriptions[client_id] = ""
        await self._send(
            client_id,
            WSContextUpdate(type="unsubscribed", detail="Unsubscribed from context updates"),
        )

    async def broadcast_context_update(
        self,
        messages: list[dict[str, Any]],
        stats: dict[str, Any] | None = None,
        pruned_count: int = 0,
        session_id: str | None = None,
    ) -> None:
        """Broadcast a context update to all subscribed clients.

        Args:
            messages: List of context message dicts
            stats: Optional context window statistics
            pruned_count: Number of messages pruned in this update
            session_id: Optional session ID to filter subscribers
        """
        update = WSContextUpdate(
            type="context_update",
            session_id=session_id,
            messages=messages,
            stats=stats,
            pruned_count=pruned_count,
        )
        async with self._lock:
            # Filter by session if specified
            target_clients = {
                cid: ws
                for cid, ws in self._connections.items()
                if session_id is None or self._subscriptions.get(cid) in (session_id, "")
            }

        tasks = [self._send(cid, update) for cid, ws in target_clients.items()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_stats_update(self, stats: dict[str, Any]) -> None:
        """Broadcast a stats-only update (no messages changed).

        Args:
            stats: Context window statistics dict
        """
        update = WSContextUpdate(type="stats_update", stats=stats)
        async with self._lock:
            tasks = [self._send(cid, update) for cid in self._connections]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_pruning_event(self, pruned_count: int, stats: dict[str, Any]) -> None:
        """Broadcast a pruning event notification.

        Args:
            pruned_count: Number of messages pruned
            stats: Updated context window statistics
        """
        update = WSContextUpdate(
            type="pruning_event",
            pruned_count=pruned_count,
            stats=stats,
            detail=f"Pruned {pruned_count} messages from context window",
        )
        async with self._lock:
            tasks = [self._send(cid, update) for cid in self._connections]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def handle_client_message(self, client_id: str, raw: bytes) -> None:
        """Process an incoming message from a WebSocket client.

        Args:
            client_id: Client identifier
            raw: Raw message bytes
        """
        try:
            data = json.loads(raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._send(
                client_id,
                WSContextUpdate(
                    type="error",
                    detail="Invalid JSON message",
                ),
            )
            return

        msg_type = data.get("type", "")

        if msg_type == "subscribe":
            session_id = data.get("session_id", "") or ""
            await self.subscribe(client_id, session_id)
        elif msg_type == "unsubscribe":
            await self.unsubscribe(client_id)
        elif msg_type == "ping":
            await self._send(
                client_id,
                WSContextUpdate(type="heartbeat", detail="pong"),
            )
        else:
            await self._send(
                client_id,
                WSContextUpdate(
                    type="error",
                    detail=f"Unknown message type: {msg_type}",
                ),
            )

    async def _send(self, client_id: str, update: WSContextUpdate) -> None:
        """Send a message to a specific client.

        Args:
            client_id: Target client ID
            update: Update payload to send
        """
        try:
            async with self._lock:
                websocket = self._connections.get(client_id)
            if websocket is None:
                return
            await websocket.send_text(update.model_dump_json())
        except Exception as exc:  # pragma: no cover — connection may have dropped
            logger.warning(f"Failed to send to client {client_id}: {exc}")
            await self.disconnect(client_id)


# Global streamer instance (created per-app in lifespan)
_ws_streamer: WebSocketContextStreamer | None = None


def _get_streamer() -> WebSocketContextStreamer:
    """Get the global WebSocket streamer instance."""
    if _ws_streamer is None:
        raise RuntimeError("WebSocket streamer not initialized")
    return _ws_streamer


async def websocket_context_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time context window streaming.

    Clients connect and send JSON messages to subscribe/unsubscribe:

        # Subscribe to all context updates:
        {{"type": "subscribe", "session_id": ""}}

        # Subscribe to a specific session:
        {{"type": "subscribe", "session_id": "my-session-123"}}

        # Unsubscribe:
        {{"type": "unsubscribe"}}

        # Heartbeat:
        {{"type": "ping"}}

    Server pushes context updates as JSON:

        # Context update:
        {{"type": "context_update", "messages": [...], "stats": {{...}}, "timestamp": "..."}}

        # Pruning event:
        {{"type": "pruning_event", "pruned_count": 3, "stats": {{...}}, "detail": "..."}}

        # Stats update:
        {{"type": "stats_update", "stats": {{...}}}}

        # Heartbeat response:
        {{"type": "heartbeat", "detail": "pong"}}

    """
    streamer = _get_streamer()
    client_id = await streamer.connect(websocket)

    # Send initial connection confirmation
    await streamer._send(
        client_id,
        WSContextUpdate(
            type="subscribed",
            detail='Connected. Send {"type": "subscribe"} to receive updates.',
        ),
    )

    try:
        while True:
            raw = await websocket.receive_bytes()
            await streamer.handle_client_message(client_id, raw)
    except WebSocketDisconnect:
        logger.debug(f"WebSocket client {client_id} disconnected")
    except Exception as exc:
        logger.warning(f"WebSocket error for client {client_id}: {exc}")
    finally:
        await streamer.disconnect(client_id)


def _get_allowed_origins() -> list[str]:
    """Parse ALLOWED_ORIGINS env var into a list of origins."""
    origins_env = os.environ.get("ALLOWED_ORIGINS", "")
    if not origins_env:
        return ["http://localhost:3000", "http://localhost:8080"]
    return [o.strip() for o in origins_env.split(",") if o.strip()]


def _build_cors_config() -> dict[str, Any]:
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
    global _episodic_memory, _semantic_memory, _procedural_memory, _ws_streamer
    setup_telemetry()
    data_dir = os.environ.get("DATA_DIR", "data")
    _episodic_memory = EpisodicMemory(storage_path=f"{data_dir}/episodic.json")
    _semantic_memory = SemanticMemory(db_path=f"{data_dir}/semantic.db")
    _procedural_memory = ProceduralMemory(storage_path=f"{data_dir}/procedural.json")
    _ws_streamer = WebSocketContextStreamer()
    logger.info(f"WebSocket streamer initialized with {len(_ws_streamer._connections)} connections")
    yield
    _episodic_memory = _semantic_memory = _procedural_memory = None
    _ws_streamer = None


# #123 turn 2: spec/docs paths are pinned explicitly (FastAPI defaults are
# implicit; making them explicit lets tests assert the contract directly).
OPENAPI_URL = "/openapi.json"
DOCS_URL = "/docs"
REDOC_URL = "/redoc"

app = FastAPI(
    title="Rik's Context Engine API",
    description="HTTP API for AI context and memory management",
    version="0.4.0",
    openapi_url=OPENAPI_URL,
    docs_url=DOCS_URL,
    redoc_url=REDOC_URL,
    lifespan=lifespan,
)

_cors = _build_cors_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors["allow_origins"],
    allow_credentials=_cors["allow_credentials"],
    allow_methods=_cors["allow_methods"],
    allow_headers=_cors["allow_headers"],
)

_rate_limit_config = RateLimitConfig()
app.add_middleware(RateLimitMiddleware, config=_rate_limit_config)
app.add_middleware(APIKeyAuthMiddleware)
# Tenant isolation MUST run after API-key auth: auth first, then scope.
app.add_middleware(TenantAuthMiddleware)
# Audit logging runs LAST (innermost) so it measures the downstream handler
# time and records the final status code, including 401s raised by the
# auth/tenant middleware for protected paths (#110).
app.add_middleware(AuditLogMiddleware)

# Register WebSocket endpoint (after app is defined)
app.add_api_websocket_route("/ws/v1/context/stream", websocket_context_stream)


class HealthResponse(BaseModel):
    # #123: examples ride in the OpenAPI spec via Field (turn 2).
    status: str = Field("ok", description="Liveness state", examples=["ok"])


class ModelsResponse(BaseModel):
    models: list[str] = Field(description="Available chat models", examples=[["gemma4-31b-it"]])


class ContextMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    importance: float
    tokens: int


class ContextAddResponse(BaseModel):
    message_id: str
    role: str
    tokens: int
    status: str


class ContextSummaryResponse(BaseModel):
    current_tokens: int
    max_tokens: int
    messages_count: int
    active_messages_count: int
    pruning_count: int
    last_prune_timestamp: str | None


@app.get("/health", response_model=HealthResponse, response_model_by_alias=True, tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/metrics", tags=["metrics"])
def metrics() -> Response:
    """Prometheus metrics endpoint (#103, OTel-backed #109).

    Public (no auth) so Prometheus scrapers can pull it. Uses the
    OpenTelemetry PrometheusMetricReader for exposition (version 0.0.4).
    """
    return Response(content=get_prometheus_output(), media_type="text/plain; version=0.0.4")


@app.get("/models", response_model=ModelsResponse, response_model_by_alias=True, tags=["models"])
def list_models() -> dict[str, list[str]]:
    """List available chat models."""
    return {"models": _MODELS}


@app.post("/api/chat", response_model=ChatResponse, tags=["chat"])
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Send a chat message with context memory wiring (#158).

    (a) Write: user message + assistant reply → tenant ContextWindowManager.
    (b) Read: last N messages + semantic memory recall → prompt context.
    LLM call: real provider if LLM_PROVIDER_URL set, deterministic stub
    otherwise (proves the wiring without a real LLM).
    """
    model = req.model or "gemma4:31b"
    if model not in _MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")

    tenant_id: str = request.state.tenant_id  # set by TenantAuthMiddleware
    ctx_mgr = _tenant_registry.get(tenant_id)
    sem_mem = _tenant_memory_registry.get_semantic(tenant_id)

    context_block = build_context_block(ctx_mgr, sem_mem, req.message)
    prompt = build_llm_prompt(f"Model: {model}\nUser message: {req.message}", context_block)

    # LLM call: real provider if configured, deterministic stub otherwise.
    llm_call = _default_llm_call
    reply = llm_call(prompt, model)

    # (a) Write: persist the exchange for future turns.
    remember_exchange(ctx_mgr, sem_mem, req.message, reply)

    return ChatResponse(response=reply, model=model)


@app.get("/", include_in_schema=False)
def root() -> FileResponse | MemoryExportResponse:
    """UI index, or a memory export when the UI is not deployed.

    Excluded from the OpenAPI spec (#123): the canonical export endpoint is
    GET /api/v1/memory/export; this alias preserves legacy behavior.
    """
    if _episodic_memory is not None and not os.path.exists(
        os.environ.get("UI_PATH", "ui/index.html")
    ):
        return _export_memory(None, "json", None, None, None)
    return FileResponse(os.environ.get("UI_PATH", "ui/index.html"))


# ─── Context Endpoints (tenant-scoped, #102) ──────────────────────────────────


class ContextAddRequest(BaseModel):
    role: str = Field("user", description="user | assistant | system")
    content: str = Field(..., description="Message content")
    importance: float = Field(0.5, ge=0.0, le=1.0)


@app.post(
    "/api/v1/context/messages",
    response_model=ContextAddResponse,
    tags=["context"],
)
def context_add_message(req: ContextAddRequest, request: Request) -> dict[str, Any]:
    """Append a message to the caller's tenant context window (tenant-scoped)."""
    tenant_id: str = request.state.tenant_id  # set by TenantAuthMiddleware
    if req.role not in ("user", "assistant", "system"):
        raise HTTPException(status_code=400, detail="Invalid role")
    msg = _tenant_registry.get(tenant_id).add(
        role=req.role, content=req.content, importance=req.importance
    )
    return {"message_id": msg.id, "role": msg.role, "tokens": msg.tokens, "status": "added"}


@app.get(
    "/api/v1/context/messages",
    response_model=list[ContextMessageResponse],
    tags=["context"],
)
def context_list_messages(request: Request) -> list[dict[str, Any]]:
    """List the caller's tenant context window. Isolated per tenant."""
    tenant_id: str = request.state.tenant_id
    msgs = _tenant_registry.get(tenant_id).get_messages(include_pruned=False)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "importance": m.importance,
            "tokens": m.tokens,
        }
        for m in msgs
    ]


@app.get(
    "/api/v1/context/summary",
    response_model=ContextSummaryResponse,
    tags=["context"],
)
def context_summary(request: Request) -> dict[str, Any]:
    """Context window stats for the caller's tenant only."""
    tenant_id: str = request.state.tenant_id
    stats = _tenant_registry.get(tenant_id).stats
    return {
        "current_tokens": stats.current_tokens,
        "max_tokens": stats.max_tokens,
        "messages_count": stats.messages_count,
        "active_messages_count": stats.active_messages_count,
        "pruning_count": stats.pruning_count,
        "last_prune_timestamp": (
            stats.last_prune_timestamp.isoformat() if stats.last_prune_timestamp else None
        ),
    }


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


def _export_memory(
    types: str | None,
    format: Literal["json", "yaml"],
    date_from: datetime | None,
    date_to: datetime | None,
    tags: list[str] | None,
) -> MemoryExportResponse:
    """Shared export logic (canonical endpoint + GET / alias)."""
    include_types = [t.strip() for t in types.split(",")] if types else None

    manifest = export_memory(
        episodic_memory=_episodic_memory,
        semantic_memory=_semantic_memory,
        procedural_memory=_procedural_memory,
        include_types=include_types,
        date_from=date_from,
        date_to=date_to,
        tags=tags,
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


@app.get("/api/v1/memory/export", response_model=MemoryExportResponse, tags=["memory"])
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
    """Export memory tiers as JSON or YAML (tenant-scoped via X-Tenant-Id)."""
    if format is None:
        format = "json"
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    return _export_memory(types, format, date_from, date_to, tag_list)


@app.post("/api/v1/memory/import", response_model=MemoryImportResponse, tags=["memory"])
def import_memory_api(req: MemoryImportRequest) -> MemoryImportResponse:
    """Import memory tiers from a JSON or YAML manifest (tenant-scoped)."""
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
    # Critical-operation audit (memory.add/import) — in-process hook (#110).
    try:
        _audit_tenant = os.environ.get("RIKS_TENANT_ID", "").strip() or "unauthenticated"
        get_audit_log(_audit_tenant).record_operation(
            CRITICAL_MEMORY_IMPORT,
            endpoint="/api/v1/memory/import",
            method="POST",
            status=200,
        )
    except Exception:  # auditing must never break the import
        pass

    return MemoryImportResponse(
        imported=imported,
        schema_version=manifest.metadata.schema_version,
    )


# ─── Audit Log Endpoint (#110) ──────────────────────────────────────────────


class AuditEntryResponse(BaseModel):
    id: str
    timestamp: str
    tenant: str
    endpoint: str
    method: str
    status: int
    latency_ms: float
    user: str
    role: str
    category: str


class AuditLogResponse(BaseModel):
    tenant: str
    total: int
    limit: int
    offset: int
    entries: list[AuditEntryResponse]


@app.get("/api/v1/audit", response_model=AuditLogResponse, tags=["audit"])
def audit_log(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=1000, description="Max entries to return")] = 100,
    offset: Annotated[int, Query(ge=0, description="Entries to skip")] = 0,
    category: Annotated[
        str | None, Query(description="Filter by category (e.g. memory.import)")
    ] = None,
    endpoint: Annotated[str | None, Query(description="Filter by endpoint path")] = None,
) -> AuditLogResponse:
    """List the audit log for the caller's tenant (tenant-scoped, #110).

    Regular users see only their own tenant's entries. When the
    ``RIKS_AUDIT_ADMIN`` env var is enabled, a caller whose API key is a
    registered admin may read ANY tenant's log via the ``?tenant=`` param.
    """
    tenant_id: str = request.state.tenant_id  # set by TenantAuthMiddleware
    requested_tenant = tenant_id
    if os.environ.get("RIKS_AUDIT_ADMIN", "").strip().lower() in {"1", "true", "yes", "on"}:
        role = "admin" if is_admin_api_key(getattr(request.state, "api_key", None)) else "regular"
        if role == "admin":
            requested_tenant = request.query_params.get("tenant") or tenant_id

    store = get_audit_log(requested_tenant)
    entries = store.query(limit=limit, offset=offset, category=category, endpoint=endpoint)
    return AuditLogResponse(
        tenant=requested_tenant,
        total=store.total(),
        limit=limit,
        offset=offset,
        entries=[
            AuditEntryResponse(
                id=e.id,
                timestamp=e.timestamp,
                tenant=e.tenant,
                endpoint=e.endpoint,
                method=e.method,
                status=e.status,
                latency_ms=e.latency_ms,
                user=e.user,
                role=e.role,
                category=e.category,
            )
            for e in entries
        ],
    )


@app.post("/api/v1/audit/operation", response_model=AuditEntryResponse, tags=["audit"])
def audit_record_operation(
    request: Request,
    category: Annotated[str, Query(description="Operation category (e.g. context.clear)")],
    endpoint: Annotated[str, Query(description="Endpoint path the operation touched")],
    method: Annotated[str, Query(description="HTTP method")],
    status: Annotated[int, Query(ge=100, le=599)] = 200,
) -> AuditEntryResponse:
    """Record a critical in-process operation in the tenant's audit log (#110)."""
    tenant_id: str = request.state.tenant_id
    role = "admin" if is_admin_api_key(getattr(request.state, "api_key", None)) else "regular"
    entry = get_audit_log(tenant_id).record_operation(
        category, endpoint=endpoint, method=method, status=status, role=role
    )
    return AuditEntryResponse(
        id=entry.id,
        timestamp=entry.timestamp,
        tenant=entry.tenant,
        endpoint=entry.endpoint,
        method=entry.method,
        status=entry.status,
        latency_ms=entry.latency_ms,
        user=entry.user,
        role=entry.role,
        category=entry.category,
    )


# ─── OpenAPI examples (#123) ─────────────────────────────────────────────────
# FastAPI serves /openapi.json + /docs + /redoc from the URLs pinned at app
# construction (OPENAPI_URL/DOCS_URL/REDOC_URL, #123 turn 2); the spec paths
# are NOT in _API_KEY_PROTECTED_PATHS, so auth/tenant middleware never blocks
# them. Examples enrich the auto-generated spec with real payloads.

_OPENAPI_INFO_EXAMPLES: dict[str, dict[str, Any]] = {
    "POST /api/v1/context/messages": {
        "request": {
            "role": "user",
            "content": "User asked about shipping to Germany",
            "importance": 0.8,
        },
        "response_200": {
            "message_id": "cm_8f2e1a",
            "role": "user",
            "tokens": 9,
            "status": "added",
        },
    },
    "GET /api/v1/context/messages": {
        "response_200": [
            {
                "id": "cm_8f2e1a",
                "role": "user",
                "content": "User asked about shipping to Germany",
                "timestamp": "2026-08-18T22:00:00Z",
                "importance": 0.8,
                "tokens": 9,
            }
        ],
    },
    "GET /api/v1/context/summary": {
        "response_200": {
            "current_tokens": 412,
            "max_tokens": 32000,
            "messages_count": 7,
            "active_messages_count": 7,
            "pruning_count": 0,
            "last_prune_timestamp": None,
        },
    },
    "GET /api/v1/memory/export": {
        "response_200": {
            "export_id": "exp_20260818_ab12cd",
            "schema_version": "1.0",
            "counts": {"episodic": 2, "semantic": 1, "procedural": 0},
            "data": '{"metadata": {"export_id": "exp_20260818_ab12cd"}}',
        },
    },
    "POST /api/v1/memory/import": {
        "request": {
            "content": '{"schema_version": "1.0", "episodic": []}',
            "format": "json",
            "merge": True,
        },
        "response_200": {
            "imported": {"episodic": 0, "semantic": 0, "procedural": 0},
            "schema_version": "1.0",
        },
    },
    "POST /api/chat": {
        "request": {"message": "Merhaba, staging deploy ne durumda?"},
        "response_200": {
            "response": "[gemma4-31b-it] Mesajını aldım: ...",
            "model": "gemma4-31b-it",
        },
    },
    "GET /health": {"response_200": {"status": "ok"}},
    "GET /models": {"response_200": {"models": ["gemma4-31b-it"]}},
}


def _apply_openapi_examples() -> None:
    """Attach example payloads to endpoint operations in the OpenAPI spec."""
    spec = app.openapi()
    for path, ops in spec.get("paths", {}).items():
        for verb, op in ops.items():
            if verb not in {"get", "post", "put", "delete", "patch"}:
                continue
            examples = _OPENAPI_INFO_EXAMPLES.get(f"{verb.upper()} {path}")
            if not examples:
                continue
            if "request" in examples and "requestBody" in op:
                op["requestBody"]["content"]["application/json"]["examples"] = {
                    "default": {"value": examples["request"]}
                }
            for key, body in examples.items():
                if key.startswith("response_") and key[9:] in op.get("responses", {}):
                    resp = op["responses"][key[9:]]
                    if "content" in resp:
                        resp["content"]["application/json"]["examples"] = {
                            "default": {"value": body}
                        }


# Build the spec once (with examples) at import time; FastAPI caches the
# result and serves /openapi.json + /docs from it.
_apply_openapi_examples()
app.openapi()
