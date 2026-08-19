"""Multi-tenant isolation primitives (#102).

Every context / memory operation is scoped to a tenant. A tenant is
identified by an opaque string; the engine never mixes data across
tenants:

- HTTP layer: ``TenantAuthMiddleware`` validates the ``X-Tenant-Id``
  header on protected paths (missing/empty/invalid -> 401, consistent).
- MCP layer: context tools are served from per-tenant
  :class:`ContextWindowManager` instances created by
  :class:`TenantContextRegistry`, so tenant A's context window is
  structurally invisible to tenant B.
- Query filter: :func:`assert_same_tenant` guards any direct query that
  could leak one tenant's records to another.

Scope note: tenant registration/management and RBAC are OUT of scope
here (tracked under #110 access control). This module only enforces
isolation + header validation.
"""

from __future__ import annotations

import os
import re
import threading

from riks_context_engine.context.manager import ContextWindowManager
from riks_context_engine.memory.episodic import EpisodicMemory
from riks_context_engine.memory.procedural import ProceduralMemory
from riks_context_engine.memory.semantic import SemanticMemory

#: Header carrying the tenant identifier on HTTP requests.
TENANT_HEADER = "X-Tenant-Id"

#: Tenant ids must be 1-64 chars of [a-zA-Z0-9._-]. This rejects empty
#: ids, whitespace, path separators, control chars and header
#: injection attempts in one consistent rule (all violations -> 401).
TENANT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class TenantValidationError(Exception):
    """Raised when a tenant identifier is missing or malformed."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def validate_tenant_id(raw: str | None) -> str:
    """Validate a raw tenant id; return it normalized (trimmed).

    Raises:
        TenantValidationError: if missing, empty, or malformed.
    """
    if raw is None:
        raise TenantValidationError(f"Missing {TENANT_HEADER} header")
    tenant = raw.strip()
    if not tenant:
        raise TenantValidationError(f"{TENANT_HEADER} header is empty")
    if not TENANT_ID_RE.match(tenant):
        raise TenantValidationError(
            f"Invalid {TENANT_HEADER}: must match [A-Za-z0-9._-] (1-64 chars)"
        )
    return tenant


def assert_same_tenant(requested: str | None, record_tenant: str, field: str = "record") -> None:
    """Guard a query so it can only ever touch the caller's own tenant.

    Raises:
        TenantValidationError: when ``requested`` differs from the
        record's tenant. Callers map this to 404/403 so that foreign
        records are indistinguishable from non-existent ones.
    """
    if requested is None or requested != record_tenant:
        # Do NOT echo the record's tenant id in the error (no oracle).
        raise TenantValidationError(f"{field} does not belong to this tenant")


def tenant_store_paths(data_dir: str, tenant_id: str | None) -> tuple[str, str, str]:
    """Return (semantic_db, episodic_json, procedural_json) for a tenant.

    When ``tenant_id`` is None or empty, returns default (legacy) paths.
    """
    tenant = (tenant_id or "").strip()
    if not tenant:
        return (
            os.path.join(data_dir, "semantic.db"),
            os.path.join(data_dir, "episodic.json"),
            os.path.join(data_dir, "procedural.json"),
        )
    base = os.path.join(data_dir, "tenants", tenant)
    return (
        os.path.join(base, "semantic.db"),
        os.path.join(base, "episodic.json"),
        os.path.join(base, "procedural.json"),
    )


class TenantContextRegistry:
    """Per-tenant :class:`ContextWindowManager` instances.

    Isolation is structural: each tenant gets its own manager, so a
    query for tenant B can never see tenant A's messages — there is no
    shared list to filter.
    """

    def __init__(self, max_tokens: int = 50_000) -> None:
        self._managers: dict[str, ContextWindowManager] = {}
        self._lock = threading.Lock()
        self._max_tokens = max_tokens

    def get(self, tenant_id: str) -> ContextWindowManager:
        """Return the context manager for ``tenant_id`` (creating it if needed).

        Args:
            tenant_id: A *validated* tenant id (run through
                :func:`validate_tenant_id` first).
        """
        with self._lock:
            mgr = self._managers.get(tenant_id)
            if mgr is None:
                mgr = ContextWindowManager(max_tokens=self._max_tokens)
                self._managers[tenant_id] = mgr
            return mgr

    def has(self, tenant_id: str) -> bool:
        with self._lock:
            return tenant_id in self._managers


class TenantMemoryRegistry:
    """Per-tenant memory store instances (semantic, episodic, procedural).

    Same structural isolation as TenantContextRegistry: each tenant gets
    its own store instances, backed by tenant-scoped file paths.
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = data_dir
        self._semantic: dict[str, SemanticMemory] = {}
        self._episodic: dict[str, EpisodicMemory] = {}
        self._procedural: dict[str, ProceduralMemory] = {}
        self._lock = threading.Lock()

    def get_semantic(self, tenant_id: str) -> SemanticMemory:
        with self._lock:
            mem = self._semantic.get(tenant_id)
            if mem is None:
                sem_db, _, _ = tenant_store_paths(self._data_dir, tenant_id)
                mem = SemanticMemory(db_path=sem_db)
                self._semantic[tenant_id] = mem
            return mem

    def get_episodic(self, tenant_id: str) -> EpisodicMemory:
        with self._lock:
            mem = self._episodic.get(tenant_id)
            if mem is None:
                _, epi_json, _ = tenant_store_paths(self._data_dir, tenant_id)
                mem = EpisodicMemory(storage_path=epi_json)
                self._episodic[tenant_id] = mem
            return mem

    def get_procedural(self, tenant_id: str) -> ProceduralMemory:
        with self._lock:
            mem = self._procedural.get(tenant_id)
            if mem is None:
                _, _, proc_json = tenant_store_paths(self._data_dir, tenant_id)
                mem = ProceduralMemory(storage_path=proc_json)
                self._procedural[tenant_id] = mem
            return mem
