"""Request handlers for each MCP tool."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..context.manager import ContextWindowManager
from ..memory import EpisodicMemory, ProceduralMemory, SemanticMemory
from ..multi_tenant import (
    TenantContextRegistry,
    TenantMemoryRegistry,
    TenantValidationError,
    validate_tenant_id,
)

logger = logging.getLogger(__name__)


class TenantIsolationError(Exception):
    """Raised when a tool call fails tenant validation/isolation."""


class SemanticWriteParams(BaseModel, extra="forbid"):
    tenant_id: str
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=512)
    object: str | None = Field(default=None, max_length=4096)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ToolHandler:
    """Wires MCP tools to the underlying memory/context components."""

    def __init__(
        self,
        episodic_memory: EpisodicMemory | None = None,
        semantic_memory: SemanticMemory | None = None,
        procedural_memory: ProceduralMemory | None = None,
        context_manager: ContextWindowManager | None = None,
        data_dir: str | None = None,
        tenant_registry: TenantContextRegistry | None = None,
    ):
        self.data_dir = data_dir or "data"
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._procedural = procedural_memory
        self._context = context_manager
        self._tenant_registry = tenant_registry or TenantContextRegistry()
        self._memory_registry = TenantMemoryRegistry(data_dir=self.data_dir)

    # -- Lazy initialisers ---------------------------------------------------

    def _get_episodic(self, tenant_id: str | None = None) -> EpisodicMemory:
        if tenant_id:
            return self._memory_registry.get_episodic(tenant_id)
        if self._episodic is None:
            self._episodic = EpisodicMemory(f"{self.data_dir}/episodic.json")
        return self._episodic

    def _get_semantic(self, tenant_id: str | None = None) -> SemanticMemory:
        if tenant_id:
            return self._memory_registry.get_semantic(tenant_id)
        if self._semantic is None:
            self._semantic = SemanticMemory(f"{self.data_dir}/semantic.db")
        return self._semantic

    def _get_procedural(self, tenant_id: str | None = None) -> ProceduralMemory:
        if tenant_id:
            return self._memory_registry.get_procedural(tenant_id)
        if self._procedural is None:
            self._procedural = ProceduralMemory(f"{self.data_dir}/procedural.json")
        return self._procedural

    def _get_context(self) -> ContextWindowManager:
        if self._context is None:
            self._context = ContextWindowManager()
        return self._context

    # -- Tool implementations -------------------------------------------------

    def episodic_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search episodic memory by free-text query."""
        query = params.get("query", "")
        limit = params.get("limit", 10)

        try:
            entries = self._get_episodic().query(query, limit=limit)
            return {
                "entries": [
                    {
                        "id": e.id,
                        "content": e.content,
                        "importance": e.importance,
                        "timestamp": e.timestamp.isoformat(),
                        "tags": e.tags or [],
                    }
                    for e in entries
                ]
            }
        except Exception as exc:
            logger.error("episodic_search failed: %s", exc)
            raise

    def semantic_query(self, params: dict[str, Any]) -> dict[str, Any]:
        """Query semantic memory by subject/predicate or free-text."""
        subject = params.get("subject")
        predicate = params.get("predicate")
        query_text = params.get("query")
        limit = params.get("limit", 10)

        try:
            semantic = self._get_semantic()
            if query_text:
                entries = semantic.recall(query_text)[:limit]
            else:
                entries = semantic.query(subject=subject, predicate=predicate)[:limit]

            return {
                "entries": [
                    {
                        "id": e.id,
                        "subject": e.subject,
                        "predicate": e.predicate,
                        "object": e.object,
                        "confidence": e.confidence,
                    }
                    for e in entries
                ]
            }
        except Exception as exc:
            logger.error("semantic_query failed: %s", exc)
            raise

    def semantic_write(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write a semantic triple to tenant-scoped memory (#108)."""
        try:
            validated = SemanticWriteParams(**params)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(loc) for loc in first["loc"])
            raise TenantIsolationError(
                f"Validation failed on field '{field}': {first['msg']}"
            ) from exc

        try:
            tenant_id = validate_tenant_id(validated.tenant_id)
        except TenantValidationError as exc:
            raise TenantIsolationError(str(exc)) from exc

        semantic = self._get_semantic(tenant_id)
        entry = semantic.add(
            subject=validated.subject,
            predicate=validated.predicate,
            object=validated.object,
            confidence=validated.confidence,
        )
        return {
            "id": entry.id,
            "subject": entry.subject,
            "predicate": entry.predicate,
            "object": entry.object,
            "confidence": entry.confidence,
            "status": "written",
        }

    def procedural_get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get procedural memory entries by tag or ID."""
        tag = params.get("tag")
        entry_id = params.get("entry_id")

        try:
            if entry_id:
                entry = self._get_procedural().get(entry_id)
                entries = [entry] if entry else []
            elif tag:
                # find() does keyword search; filter by tag after
                all_entries = self._get_procedural().find(tag)
                entries = [e for e in all_entries if tag in (getattr(e, "tags", []) or [])]
            else:
                entries = []

            return {
                "entries": [
                    {
                        "id": e.id,
                        "title": getattr(e, "title", ""),
                        "content": getattr(e, "content", ""),
                        "tags": getattr(e, "tags", []) or [],
                    }
                    for e in entries
                ]
            }
        except Exception as exc:
            logger.error("procedural_get failed: %s", exc)
            raise

    def memory_export(self, params: dict[str, Any]) -> dict[str, Any]:
        """Export memory tiers as JSON or YAML."""
        fmt = params.get("format", "json")
        tiers = params.get("tiers", ["episodic", "semantic", "procedural"])

        if fmt not in ("json", "yaml"):
            raise ValueError(f"Unsupported format: {fmt}. Use 'json' or 'yaml'.")

        import json

        export_data: dict[str, Any] = {}

        if "episodic" in tiers:
            episodic = self._get_episodic()
            export_data["episodic"] = [
                {
                    "id": e.id,
                    "content": e.content,
                    "importance": e.importance,
                    "timestamp": e.timestamp.isoformat(),
                    "tags": e.tags or [],
                }
                for e in episodic._entries.values()
            ]

        if "semantic" in tiers:
            semantic = self._get_semantic()
            all_entries = semantic.query()[:100]
            export_data["semantic"] = [
                {
                    "id": e.id,
                    "subject": e.subject,
                    "predicate": e.predicate,
                    "object": e.object,
                    "confidence": e.confidence,
                }
                for e in all_entries
            ]

        if "procedural" in tiers:
            procedural = self._get_procedural()
            export_data["procedural"] = [
                {
                    "id": p.id,
                    "title": getattr(p, "title", ""),
                    "content": getattr(p, "content", ""),
                    "tags": getattr(p, "tags", []) or [],
                }
                for p in list(procedural.procedures.values())
            ]

        if fmt == "yaml":
            import yaml

            return {"yaml": yaml.dump(export_data, default_flow_style=False)}

        return {"json": json.dumps(export_data, indent=2, default=str)}

    def context_add_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add a message to the caller's tenant context window (#102)."""
        try:
            tenant_id = validate_tenant_id(params.get("tenant_id"))
        except TenantValidationError as exc:
            raise TenantIsolationError(str(exc)) from exc
        role = params.get("role", "user")
        content = params.get("content", "")
        importance = params.get("importance", 0.5)
        is_grounding = params.get("is_grounding", False)

        try:
            # Per-tenant manager: structural isolation (A can't see B).
            msg = self._tenant_registry.get(tenant_id).add(
                role=role,
                content=content,
                importance=importance,
                is_grounding=is_grounding,
            )
            return {
                "message_id": msg.id,
                "role": msg.role,
                "tokens": msg.tokens,
                "status": "added",
            }
        except Exception as exc:
            logger.error("context_add_message failed: %s", exc)
            raise

    def context_get_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get the caller's tenant context window statistics (#102)."""
        try:
            tenant_id = validate_tenant_id(params.get("tenant_id"))
        except TenantValidationError as exc:
            raise TenantIsolationError(str(exc)) from exc
        ctx = self._tenant_registry.get(tenant_id)
        stats = ctx.stats
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

    def health_check(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return server health status."""
        del params
        return {"status": "ok", "version": "0.2.0"}


def create_handler(data_dir: str | None = None) -> ToolHandler:
    """Factory for a ToolHandler with default or configured storage."""
    return ToolHandler(data_dir=data_dir)
