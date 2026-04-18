"""Memory export/import for cross-model portability.

Supports JSON and YAML formats with selective export by type, date range, and tags.
Schema versioning ensures forward/backward compatibility.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "1.0"


class MemoryFormat(Enum):
    JSON = "json"
    YAML = "yaml"


@dataclass
class ExportMetadata:
    """Metadata attached to every export file."""

    schema_version: str = SCHEMA_VERSION
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tool: str = "riks-context-engine"
    export_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class ExportManifest:
    """Top-level export file structure."""

    metadata: ExportMetadata
    episodic: list[dict[str, Any]]
    semantic: list[dict[str, Any]]
    procedural: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": asdict(self.metadata),
            "episodic": self.episodic,
            "semantic": self.semantic,
            "procedural": self.procedural,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExportManifest:
        meta = ExportMetadata(**data["metadata"])
        return cls(
            metadata=meta,
            episodic=data.get("episodic", []),
            semantic=data.get("semantic", []),
            procedural=data.get("procedural", []),
        )


def _serialize_episodic_entry(entry: Any) -> dict[str, Any]:
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat(),
        "content": entry.content,
        "importance": entry.importance,
        "embedding": entry.embedding,
        "tags": entry.tags,
        "access_count": entry.access_count,
        "last_accessed": (entry.last_accessed.isoformat() if entry.last_accessed else None),
        "type": "episodic",
    }


def _serialize_semantic_entry(entry: Any) -> dict[str, Any]:
    return {
        "id": entry.id,
        "subject": entry.subject,
        "predicate": entry.predicate,
        "object": entry.object,
        "confidence": entry.confidence,
        "created_at": entry.created_at.isoformat(),
        "last_accessed": entry.last_accessed.isoformat(),
        "access_count": entry.access_count,
        "embedding": entry.embedding,
        "type": "semantic",
    }


def _serialize_procedural_entry(entry: Any) -> dict[str, Any]:
    return {
        "id": entry.id,
        "name": entry.name,
        "description": entry.description,
        "steps": entry.steps,
        "created_at": entry.created_at.isoformat(),
        "last_used": entry.last_used.isoformat(),
        "use_count": entry.use_count,
        "success_rate": entry.success_rate,
        "tags": entry.tags,
        "type": "procedural",
    }


def export_memory(
    episodic_memory: Any | None,
    semantic_memory: Any | None,
    procedural_memory: Any | None,
    include_types: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    tags: list[str] | None = None,
) -> ExportManifest:
    """Export memory tiers into a portable manifest.

    Parameters
    ----------
    episodic_memory : EpisodicMemory | None
    semantic_memory : SemanticMemory | None
    procedural_memory : ProceduralMemory | None
    include_types : list[str] | None
        Filter by memory types: ["episodic", "semantic", "procedural"].
        None means all.
    date_from : datetime | None
        Only include entries created after this UTC timestamp.
    date_to : datetime | None
        Only include entries created before this UTC timestamp.
    tags : list[str] | None
        Only include entries that have at least one of these tags (episodic/procedural only).

    Returns
    -------
    ExportManifest
    """
    if include_types is None:
        include_types = ["episodic", "semantic", "procedural"]

    episodic_entries = []
    if episodic_memory and "episodic" in include_types:
        for entry in episodic_memory.entries.values():
            if not _entry_in_date_range(entry.timestamp, date_from, date_to):
                continue
            if tags and not any(t in (entry.tags or []) for t in tags):
                continue
            episodic_entries.append(_serialize_episodic_entry(entry))

    semantic_entries = []
    if semantic_memory and "semantic" in include_types:
        for row in semantic_memory.query():
            # SemanticMemory.query() returns list[SemanticEntry]
            entry = row
            if not _entry_in_date_range(entry.created_at, date_from, date_to):
                continue
            semantic_entries.append(_serialize_semantic_entry(entry))

    procedural_entries = []
    if procedural_memory and "procedural" in include_types:
        for proc in procedural_memory.procedures.values():
            if not _entry_in_date_range(proc.created_at, date_from, date_to):
                continue
            if tags and not any(t in proc.tags for t in tags):
                continue
            procedural_entries.append(_serialize_procedural_entry(proc))

    return ExportManifest(
        metadata=ExportMetadata(),
        episodic=episodic_entries,
        semantic=semantic_entries,
        procedural=procedural_entries,
    )


def _entry_in_date_range(
    ts: datetime,
    date_from: datetime | None,
    date_to: datetime | None,
) -> bool:
    if date_from and ts < date_from:
        return False
    if date_to and ts > date_to:
        return False
    return True


def dump_manifest(manifest: ExportManifest, format: MemoryFormat, path: Path | None = None) -> str:
    """Serialize a manifest to JSON or YAML string, optionally writing to a file.

    Parameters
    ----------
    manifest : ExportManifest
    format : MemoryFormat
    path : Path | None
        If given, write to this file path as well.

    Returns
    -------
    str
        The serialized content.
    """
    data = manifest.to_dict()
    if format == MemoryFormat.JSON:
        content = json.dumps(data, indent=2, ensure_ascii=False)
    else:
        content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return content


def parse_manifest(content: str, format: MemoryFormat) -> ExportManifest:
    """Parse JSON or YAML content into an ExportManifest."""
    if format == MemoryFormat.JSON:
        data = json.loads(content)
    else:
        data = yaml.safe_load(content)

    if not isinstance(data, dict):
        raise ValueError(f"Expected object at top level, got {type(data).__name__}")

    # Schema version check
    meta = data.get("metadata", {})
    ver = meta.get("schema_version", "0.0")
    _check_schema_compat(ver)

    return ExportManifest.from_dict(data)


def _check_schema_compat(ver: str) -> None:
    """Reject manifests with incompatible schema versions."""
    ver_major = ver.split(".")[0]
    expected_major = SCHEMA_VERSION.split(".")[0]
    if ver_major != expected_major:
        raise ValueError(
            f"Schema version mismatch: got {ver}, expected {SCHEMA_VERSION}. "
            f"Major version must match ({expected_major})."
        )


# --- Import helpers ---

def _deserialize_episodic(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": data["content"],
        "importance": data.get("importance", 0.5),
        "tags": data.get("tags"),
        "embedding": data.get("embedding"),
    }


def _deserialize_semantic(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": data["subject"],
        "predicate": data["predicate"],
        "object": data.get("object"),
        "confidence": data.get("confidence", 1.0),
        "embedding": data.get("embedding"),
    }


def _deserialize_procedural(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": data["name"],
        "description": data.get("description", ""),
        "steps": data.get("steps", []),
        "tags": data.get("tags", []),
    }


def import_to_memory(
    manifest: ExportManifest,
    episodic_memory: Any | None = None,
    semantic_memory: Any | None = None,
    procedural_memory: Any | None = None,
    merge: bool = True,
) -> dict[str, int]:
    """Import a manifest back into memory stores.

    Parameters
    ----------
    manifest : ExportManifest
    episodic_memory : EpisodicMemory | None
    semantic_memory : SemanticMemory | None
    procedural_memory : ProceduralMemory | None
    merge : bool
        If True, skip entries whose id already exists (upsert-like).
        If False, replace all existing entries first.

    Returns
    -------
    dict[str, int]
        Counts of imported entries per tier: {"episodic": N, "semantic": N, "procedural": N}
    """
    imported = {"episodic": 0, "semantic": 0, "procedural": 0}

    existing_ids: set[str] = set()
    if not merge and episodic_memory:
        for eid in list(episodic_memory.entries.keys()):
            episodic_memory.delete(eid)
        existing_ids = set()

    if episodic_memory is not None:
        if not merge:
            existing_ids = set(episodic_memory.entries.keys())
        for entry_data in manifest.episodic:
            if entry_data["id"] in existing_ids:
                continue
            kwargs = _deserialize_episodic(entry_data)
            episodic_memory.add(**kwargs)
            existing_ids.add(entry_data["id"])
            imported["episodic"] += 1

    # Semantic: query all existing ids first
    if semantic_memory is not None and not merge:
        for row in semantic_memory.query():
            semantic_memory.delete(row.id)

    if semantic_memory is not None:
        if not merge:
            existing_ids = set()
            for row in semantic_memory.query():
                existing_ids.add(row.id)
        for entry_data in manifest.semantic:
            if entry_data["id"] in existing_ids:
                continue
            kwargs = _deserialize_semantic(entry_data)
            semantic_memory.add(**kwargs)
            existing_ids.add(entry_data["id"])
            imported["semantic"] += 1

    if procedural_memory and not merge:
        for pid in list(procedural_memory.procedures.keys()):
            procedural_memory.delete(pid)
        existing_ids = set()

    if procedural_memory is not None:
        if not merge:
            existing_ids = set(procedural_memory.procedures.keys())
        for entry_data in manifest.procedural:
            if entry_data["id"] in existing_ids:
                continue
            kwargs = _deserialize_procedural(entry_data)
            procedural_memory.store(**kwargs)
            existing_ids.add(entry_data["id"])
            imported["procedural"] += 1

    return imported