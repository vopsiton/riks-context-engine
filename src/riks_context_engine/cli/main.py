"""Command-line interface for Rik's Context Engine.

#124 (turn 1): `riks memory add` and `riks memory query` are implemented
against the real memory stores. Other commands report "not implemented yet"
with exit code 1 instead of the old fake "Command executed successfully".
"""

from __future__ import annotations

import argparse
import os
import sys


# CLI storage locations — overridable via env for tests and deployments.
# Evaluated lazily (at store-construction time) so monkeypatched env vars in
# tests take effect without reloading the module.
def _store_paths() -> tuple[str, str, str]:
    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    return (
        os.environ.get("RIKS_SEMANTIC_DB", os.path.join(data_dir, "semantic.db")),
        os.environ.get("RIKS_EPISODIC_JSON", os.path.join(data_dir, "episodic.json")),
        os.environ.get("RIKS_PROCEDURAL_JSON", os.path.join(data_dir, "procedural.json")),
    )


def _err(msg: str) -> int:
    """Print a real error to stderr and return a non-zero exit code."""
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _memory_store_paths() -> tuple[str, str, str]:
    """Per-tenant memory store paths (mirrors server.py tenant contract #102).

    RIKS_TENANT_ID empty/absent → default tenant (shared legacy paths).
    """
    sem_db, epi_json, proc_json = _store_paths()
    tenant = os.environ.get("RIKS_TENANT_ID", "").strip()
    if not tenant:
        return sem_db, epi_json, proc_json
    base = os.path.join(os.environ.get("RIKS_DATA_DIR", "data"), "tenants", tenant)
    return (
        os.path.join(base, "semantic.db"),
        os.path.join(base, "episodic.json"),
        os.path.join(base, "procedural.json"),
    )


def _parse_steps(raw: str) -> list[str]:
    """Parse a --steps value: newline-separated, or JSON array if it starts with '['."""
    raw = raw.strip()
    if raw.startswith("["):
        import json

        try:
            steps = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--steps is not valid JSON: {exc}") from exc
        if not isinstance(steps, list) or not all(isinstance(s, str) for s in steps):
            raise ValueError("--steps JSON must be an array of strings")
        return steps
    steps = [line.strip() for line in raw.splitlines() if line.strip()]
    if not steps:
        raise ValueError("--steps must contain at least one step")
    return steps


def _parse_steps_strict(raw: str) -> list[str]:
    """Strict --steps parse for procedural add: must be newline-separated or a JSON array."""
    raw = raw.strip()
    if raw.startswith("["):
        try:
            return _parse_steps(raw)
        except ValueError:
            raise
    if "\n" not in raw:
        raise ValueError(
            "--steps must be newline-separated or a JSON array; for a single step wrap it in quotes with at least one newline or use JSON: ['step']"
        )
    return _parse_steps(raw)


def cmd_memory_add(args: argparse.Namespace, text: str | None, extras: list[str]) -> int:
    """Implement `riks memory add` against the real memory stores.

    ``text``/``extras`` are the extra positionals captured by parse_known_args
    (argparse cannot declare two positionals on one subparser).
    """
    sem_db, epi_json, proc_json = _memory_store_paths()
    if args.type == "episodic":
        if not text:
            return _err(
                "usage: riks memory add --type episodic <content> "
                '(e.g. riks memory add --type episodic "User asked about shipping")'
            )
        from riks_context_engine.memory.episodic import EpisodicMemory

        try:
            mem = EpisodicMemory(storage_path=epi_json)
            entry = mem.add(text)
        except Exception as exc:  # noqa: BLE001 — surface real storage errors
            return _err(f"failed to add episodic memory: {exc}")
        print(f"added episodic entry {entry.id}: {text}")
        return 0

    if args.type == "semantic":
        if not text or "=" not in text:
            return _err(
                "usage: riks memory add --type semantic <subject>=<predicate>[=<object>] "
                "(e.g. riks memory add --type semantic Vahit=is=DevSecOps)"
            )
        parts = text.split("=", 2)
        subject, predicate = parts[0], parts[1]
        obj = parts[2] if len(parts) > 2 else None
        if not subject or not predicate:
            return _err("subject and predicate must be non-empty (subject=predicate[=object])")
        from riks_context_engine.memory.semantic import SemanticMemory

        try:
            mem = SemanticMemory(db_path=sem_db)
            entry = mem.add(subject=subject, predicate=predicate, object=obj)
        except Exception as exc:  # noqa: BLE001 — surface real storage errors
            return _err(f"failed to add semantic memory: {exc}")
        shown = f"{subject} {predicate}" + (f" {obj}" if obj else "")
        print(f"added semantic entry {entry.id}: {shown}")
        return 0

    # procedural — the procedure name is the first extra positional.
    name = extras[0] if extras else None
    if not name:
        return _err(
            'usage: riks memory add --type procedural <name> --steps "step1\\nstep2" '
            '(or --steps \'["step1", "step2"]\')'
        )
    if not args.steps:
        return _err("procedural add requires --steps (newline-separated or JSON array)")
    try:
        steps = _parse_steps_strict(args.steps)
    except ValueError as exc:
        return _err(str(exc))
    from riks_context_engine.memory.procedural import ProceduralMemory

    try:
        mem = ProceduralMemory(storage_path=proc_json)
        proc = mem.store(name=name, description=args.description or name, steps=steps)
    except Exception as exc:  # noqa: BLE001 — surface real storage errors
        return _err(f"failed to add procedural memory: {exc}")
    print(f"added procedure {proc.id}: {proc.name} ({len(steps)} steps)")
    return 0


def cmd_memory_query(args: argparse.Namespace, text: str | None) -> int:
    """Implement `riks memory query` against the real memory stores."""
    sem_db, epi_json, proc_json = _memory_store_paths()
    if not text:
        return _err("usage: riks memory query <term> (search term required)")

    if args.type == "episodic":
        from riks_context_engine.memory.episodic import EpisodicMemory

        try:
            mem = EpisodicMemory(storage_path=epi_json)
            results = mem.query(text, limit=args.limit)
        except Exception as exc:  # noqa: BLE001
            return _err(f"failed to query episodic memory: {exc}")
        if not results:
            print("no episodic matches")
            return 0
        for e in results:
            tags = f" [{', '.join(e.tags)}]" if e.tags else ""
            print(f"{e.id}  importance={e.importance:.2f}  {e.content}{tags}")
        return 0

    if args.type == "semantic":
        from riks_context_engine.memory.semantic import SemanticMemory

        # Semantic query is subject/predicate-filter based; the search term is
        # matched against the subject.
        try:
            mem = SemanticMemory(db_path=sem_db)
            results = mem.query(subject=text)[: args.limit]
        except Exception as exc:  # noqa: BLE001
            return _err(f"failed to query semantic memory: {exc}")
        if not results:
            print("no semantic matches")
            return 0
        for e in results:
            obj = f" {e.object}" if e.object else ""
            print(f"{e.id}  {e.subject} {e.predicate}{obj}  (confidence={e.confidence:.2f})")
        return 0

    # procedural
    from riks_context_engine.memory.procedural import ProceduralMemory

    try:
        mem = ProceduralMemory(storage_path=proc_json)
        results = mem.find(text)[: args.limit]
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to query procedural memory: {exc}")
    if not results:
        print("no procedural matches")
        return 0
    for p in results:
        print(f"{p.id}  {p.name}: {p.description} ({len(p.steps)} steps)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riks",
        description="Rik's Context Engine - AI memory and context management",
    )
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--session", type=str, help="Session ID to resume")
    sub = parser.add_subparsers(dest="command")

    # Memory commands
    mem = sub.add_parser("memory", help="Memory operations")
    mem.add_argument("action", choices=["add", "query", "stats"])
    mem.add_argument("--type", choices=["episodic", "semantic", "procedural"], default="episodic")
    mem.add_argument("--description", help="procedural add: procedure description")
    mem.add_argument("--steps", help="procedural add: steps (newline-separated or JSON array)")
    mem.add_argument("--limit", type=int, default=10, help="query: max results (default 10)")

    # Context commands
    ctx = sub.add_parser("context", help="Context window operations")
    ctx.add_argument("action", choices=["stats", "prune", "clear"])

    # Task commands
    task = sub.add_parser("task", help="Task operations")
    task.add_argument("goal", type=str, help="Goal to decompose")
    task.add_argument("--execute", action="store_true", help="Execute after decomposition")

    # Reflection commands
    refl = sub.add_parser("reflect", help="Self-reflection")
    refl.add_argument("--session", type=str, required=True, help="Session ID to reflect on")
    return parser


def _parse_known(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    """Parse CLI args; extra positionals (content text / search term) land in extras."""
    parser = _build_parser()
    return parser.parse_known_args(argv)


def main() -> int:
    args, extras = _parse_known()

    if args.version:
        from riks_context_engine import __version__

        print(f"riks-context-engine {__version__}")
        return 0

    if args.command is None:
        _build_parser().print_help()
        return 1

    # memory add/query are implemented against the real memory stores (#124).
    # memory stats and context/task/reflect remain out of scope for this turn
    # and report that honestly instead of pretending success.
    if args.command == "memory" and args.action in ("add", "query"):
        text = extras[0] if extras else None
        if args.action == "add":
            return cmd_memory_add(args, text, extras)
        return cmd_memory_query(args, text)

    if extras:
        print(f"error: unexpected argument(s): {' '.join(extras)}", file=sys.stderr)
        return 2

    print(f"not implemented yet: riks {args.command} {getattr(args, 'action', '') or ''}".strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
