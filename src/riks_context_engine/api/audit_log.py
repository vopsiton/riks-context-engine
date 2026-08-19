"""Audit log — tenant-scoped, JSON-backed (#110).

Every HTTP request to the FastAPI API is recorded as an audit entry
(timestamp, tenant, endpoint, method, status code, latency, user/role,
category). Critical operations (memory add/delete, context clear, task
execute) are flagged with a ``critical`` category so they can be
queried independently.

Design notes (consistent with the existing JSON persistence pattern —
``task_queue.py`` / ``data/lessons.json``):

- Storage: ``data/tenants/<tenant>/audit.json`` (tenant-scoped, like the
  memory stores and the task queue). A single-process dev/CI server uses a
  process-wide lock for thread safety; this is NOT a high-availability
  store (SQLite is intentionally not used here, per #110 scope).
- Tenant scoping: the active tenant comes from ``request.state.tenant_id``
  (set by ``TenantAuthMiddleware``). Requests without a tenant (e.g.
  ``/health``) are attributed to the ``RIKS_TENANT_ID`` env default or
  ``"unauthenticated"``.
- RBAC hook: the audit store also carries a lightweight role model
  (``admin`` vs ``regular``). Roles are assigned per API key via the
  ``RIKS_ADMIN_API_KEYS`` env var (comma-separated). Admins may read the
  audit log of ANY tenant via the ``RIKS_AUDIT_ADMIN`` env opt-in; regular
  users only their own tenant's log.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# ─── Role model (RBAC, #110) ─────────────────────────────────────────────────


def _env_list(name: str) -> list[str]:
    """Parse a comma-separated env var into a list of trimmed, non-empty items."""
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_admin_api_keys() -> frozenset[str]:
    """Return the set of API keys that map to the ``admin`` role."""
    return frozenset(_env_list("RIKS_ADMIN_API_KEYS"))


def is_admin_api_key(api_key: str | None) -> bool:
    """Return True when *api_key* is a registered admin API key.

    An empty/missing key never grants admin (consistent with the auth
    middleware: no key -> no protected access).
    """
    if not api_key:
        return False
    return api_key in load_admin_api_keys()


# ─── Audit entry model ───────────────────────────────────────────────────────


# Critical-operation categories (issue #110): memory add/delete, context
# clear, task execute. The request audit layer only sees HTTP requests; we
# classify by method+path so the *operation* is captured at the API surface.
# (Deeper in-process mutations reuse ``record_operation``.)
CRITICAL_MEMORY_ADD = "memory.add"
CRITICAL_MEMORY_DELETE = "memory.delete"
CRITICAL_CONTEXT_CLEAR = "context.clear"
CRITICAL_TASK_EXECUTE = "task.execute"
CRITICAL_MEMORY_IMPORT = "memory.import"
CRITICAL_CONTEXT_ADD = "context.add"


def _critical_category(method: str, path: str) -> str | None:
    """Map an HTTP request to a critical-operation category (or None)."""
    m = method.upper()
    if m == "POST" and path == "/api/v1/memory/import":
        return CRITICAL_MEMORY_IMPORT
    if m == "POST" and path == "/api/v1/context/messages":
        return CRITICAL_CONTEXT_ADD
    return None


@dataclass
class AuditEntry:
    """A single audit log record."""

    id: str
    timestamp: str
    tenant: str
    endpoint: str
    method: str
    status: int
    latency_ms: float
    user: str = "anonymous"
    role: str = "regular"  # admin | regular
    category: str = "request"  # request | memory.add | context.clear | task.execute | ...

    @classmethod
    def now(
        cls,
        *,
        tenant: str,
        endpoint: str,
        method: str,
        status: int,
        latency_ms: float,
        user: str = "anonymous",
        role: str = "regular",
        category: str = "request",
    ) -> AuditEntry:
        return cls(
            id=f"audit_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            tenant=tenant,
            endpoint=endpoint,
            method=method.upper(),
            status=status,
            latency_ms=round(latency_ms, 3),
            user=user,
            role=role,
            category=category,
        )


# ─── Tenant-scoped JSON store ────────────────────────────────────────────────


def _audit_path(tenant: str) -> Path:
    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    return Path(data_dir) / "tenants" / tenant / "audit.json"


class AuditLog:
    """Append-only, tenant-scoped JSON audit log (one file per tenant)."""

    def __init__(self, tenant: str, path: Path | None = None) -> None:
        self.tenant = tenant
        self.path = path or _audit_path(tenant)
        self._lock = threading.Lock()
        self._entries: list[AuditEntry] = []
        self._load()

    def _load(self) -> None:
        p = self.path
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for d in data.get("entries", []):
                self._entries.append(AuditEntry(**d))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._entries = []  # start fresh on corruption

    def _save(self) -> None:
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [asdict(e) for e in self._entries]}
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def record(
        self,
        entry: AuditEntry,
    ) -> AuditEntry:
        """Append an entry (thread-safe) and persist."""
        with self._lock:
            self._entries.append(entry)
            self._save()
        return entry

    # Convenience for critical in-process operations.
    def record_operation(
        self,
        category: str,
        *,
        endpoint: str,
        method: str,
        status: int,
        user: str = "anonymous",
        role: str = "regular",
        latency_ms: float = 0.0,
    ) -> AuditEntry:
        return self.record(
            AuditEntry.now(
                tenant=self.tenant,
                endpoint=endpoint,
                method=method,
                status=status,
                latency_ms=latency_ms,
                user=user,
                role=role,
                category=category,
            )
        )

    def query(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
        endpoint: str | None = None,
        min_status: int | None = None,
    ) -> list[AuditEntry]:
        """Return a page of entries, newest first, optionally filtered."""
        items = list(self._entries)
        if category is not None:
            items = [e for e in items if e.category == category]
        if endpoint is not None:
            items = [e for e in items if e.endpoint == endpoint]
        if min_status is not None:
            items = [e for e in items if e.status >= min_status]
        items.sort(key=lambda e: e.timestamp, reverse=True)
        if offset < 0:
            offset = 0
        return items[offset : offset + limit]

    def total(self) -> int:
        return len(self._entries)


# ─── Process-wide registry (tenant -> store) ─────────────────────────────────

_registry: dict[str, AuditLog] = {}
_registry_lock = threading.Lock()


def get_audit_log(tenant: str) -> AuditLog:
    """Return (and cache) the AuditLog for *tenant*."""
    with _registry_lock:
        if tenant not in _registry:
            _registry[tenant] = AuditLog(tenant)
        return _registry[tenant]


def _default_tenant() -> str:
    """Tenant used for requests that carry no validated tenant header."""
    return os.environ.get("RIKS_TENANT_ID", "").strip() or "unauthenticated"


def record_request(
    *,
    tenant: str,
    endpoint: str,
    method: str,
    status: int,
    latency_ms: float,
    api_key: str | None = None,
) -> AuditEntry:
    """Record an HTTP request in the tenant's audit log.

    Role is derived from the API key (admin keys -> ``admin``, otherwise
    ``regular``). Safe to call on every request; failures are swallowed so
    auditing never breaks the request path.
    """
    try:
        role = "admin" if is_admin_api_key(api_key) else "regular"
        category = _critical_category(method, endpoint) or "request"
        store = get_audit_log(tenant)
        return store.record(
            AuditEntry.now(
                tenant=tenant,
                endpoint=endpoint,
                method=method,
                status=status,
                latency_ms=latency_ms,
                role=role,
                category=category,
            )
        )
    except Exception:  # pragma: no cover - auditing must never break a request
        return AuditEntry(
            id="audit_err",
            timestamp=datetime.now(timezone.utc).isoformat(),
            tenant=tenant,
            endpoint=endpoint,
            method=method.upper(),
            status=status,
            latency_ms=0.0,
            role="regular",
            category="request",
        )


def reset_registry() -> None:
    """Drop all cached stores (test helper)."""
    with _registry_lock:
        _registry.clear()


# ─── Prometheus metrics (#103) ──────────────────────────────────────────────
#
# In-memory, global (tenant-agnostic, Prometheus-standard) collectors
# populated by the audit middleware on every request. No external
# Prometheus client library — metrics are plain dicts serialized to the
# Prometheus text exposition format (version 0.0.4) at /metrics.
#
# Process restart resets these (no HA — #105 covers durable storage).

DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

_metrics_lock = threading.Lock()
_request_count = 0  # total HTTP requests seen
_request_seconds_sum = 0.0  # cumulative request latency (seconds)
_error_count = 0  # requests with status >= 500
_bucket_counts: list[int] = [0] * len(DEFAULT_BUCKETS)  # histogram bucket counts


def observe_request(duration_s: float, status: int) -> None:
    """Update the in-memory Prometheus metrics for one request.

    ``duration_s`` is the request latency in seconds; ``status`` is the final
    HTTP status code. Errors (>=500) are counted separately.
    """
    global _request_count, _request_seconds_sum, _error_count
    with _metrics_lock:
        _request_count += 1
        _request_seconds_sum += float(duration_s)
        if status >= 500:
            _error_count += 1
        # Histogram: count the sample into each bucket it falls below (<=).
        for idx, b in enumerate(DEFAULT_BUCKETS):
            if duration_s <= b:
                _bucket_counts[idx] += 1
                break


def reset_metrics() -> None:
    """Reset all in-memory metrics (test helper)."""
    global _request_count, _request_seconds_sum, _error_count
    with _metrics_lock:
        _request_count = 0
        _request_seconds_sum = 0.0
        _error_count = 0
        for i in range(len(_bucket_counts)):
            _bucket_counts[i] = 0


def render_prometheus() -> str:
    """Render the metrics in Prometheus text exposition format (0.0.4)."""
    with _metrics_lock:
        count = _request_count
        seconds_sum = _request_seconds_sum
        errors = _error_count
        buckets = list(_bucket_counts)

    lines: list[str] = []

    lines.append("# HELP riks_request_count Total number of HTTP requests processed.")
    lines.append("# TYPE riks_request_count counter")
    lines.append(f"riks_request_count {count}")

    lines.append(
        "# HELP riks_error_count Total number of HTTP requests that errored (status >= 500)."
    )
    lines.append("# TYPE riks_error_count counter")
    lines.append(f"riks_error_count {errors}")

    # riks_request_duration_seconds: a histogram.
    lines.append("# HELP riks_request_duration_seconds HTTP request latency in seconds.")
    lines.append("# TYPE riks_request_duration_seconds histogram")
    for i, b in enumerate(DEFAULT_BUCKETS):
        lines.append(f'riks_request_duration_seconds_bucket{{le="{b}"}} {buckets[i]}')
    lines.append('riks_request_duration_seconds_bucket{le="+Inf"} ' + str(count))
    lines.append(f"riks_request_duration_seconds_sum {seconds_sum:.6f}")
    lines.append(f"riks_request_duration_seconds_count {count}")
    return "\n".join(lines) + "\n"
