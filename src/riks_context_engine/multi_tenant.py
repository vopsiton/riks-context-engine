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

import re
import threading

from riks_context_engine.context.manager import ContextWindowManager

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
