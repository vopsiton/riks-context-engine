"""Command-line interface for Rik's Context Engine.

#124: `riks memory add/query` (turn 1) and `riks context stats/prune/clear`,
`riks task <goal>`, `riks reflect --session <id>` (turn 2) are implemented
against the real stores. `riks task <goal>` queues the goal; real execution
is intentionally out of scope until the task model is clarified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from riks_context_engine.cli.task_queue import TaskQueue
from riks_context_engine.context.manager import ContextWindowManager


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
        return _parse_steps(raw)
    if "\n" not in raw:
        raise ValueError(
            "--steps must be newline-separated or a JSON array; "
            "for a single step use JSON: ['step']"
        )
    return _parse_steps(raw)


def _print_episodic_results(results: list[Any]) -> None:
    for e in results:
        tags = f" [{', '.join(e.tags)}]" if e.tags else ""
        print(f"{e.id}  importance={e.importance:.2f}  {e.content}{tags}")


def _print_semantic_results(results: list[Any]) -> None:
    for e in results:
        obj = f" {e.object}" if e.object else ""
        print(f"{e.id}  {e.subject} {e.predicate}{obj}  (confidence={e.confidence:.2f})")


def _print_procedural_results(results: list[Any]) -> None:
    for p in results:
        print(f"{p.id}  {p.name}: {p.description} ({len(p.steps)} steps)")


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
            mem: Any = EpisodicMemory(storage_path=epi_json)
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
            mem: Any = EpisodicMemory(storage_path=epi_json)
            results: list[Any] = mem.query(text, limit=args.limit)
        except Exception as exc:  # noqa: BLE001
            return _err(f"failed to query episodic memory: {exc}")
        if not results:
            print("no episodic matches")
            return 0
        _print_episodic_results(results)
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
        _print_semantic_results(results)
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
    _print_procedural_results(results)
    return 0


def _context_manager_for_tenant() -> ContextWindowManager:
    """Tenant-scoped context window manager on the shared data dir."""
    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    tenant = os.environ.get("RIKS_TENANT_ID", "").strip()
    path = (
        os.path.join(data_dir, "tenants", tenant, "context.json")
        if tenant
        else os.path.join(data_dir, "context.json")
    )
    manager = ContextWindowManager(storage_path=path)
    manager.load()
    return manager


def cmd_context_stats() -> int:
    """Report real context-window stats from the persisted store."""
    manager = _context_manager_for_tenant()
    s = manager.get_summary()
    roles: dict[str, int] = {}
    for m in manager.messages:
        roles[m.role] = roles.get(m.role, 0) + 1
    print(f"messages_total: {s['messages_count']}")
    print(f"messages_active: {s['active_messages_count']}")
    print(f"messages_pruned: {s['pruned_messages']}")
    print(f"current_tokens: {s['current_tokens']}")
    print(f"max_tokens: {s['max_tokens']}")
    print(f"tokens_remaining: {s['tokens_remaining']}")
    print(f"utilization: {s['utilization']}")
    if roles:
        dist = ", ".join(f"{role}={n}" for role, n in sorted(roles.items()))
        print(f"role_distribution: {dist}")
    return 0


def cmd_context_prune(args: argparse.Namespace) -> int:
    """Remove messages older than --older-than DAYS (optionally by role)."""
    if args.older_than is None:
        return _err("prune requires --older-than DAYS (e.g. --older-than 7)")
    if args.older_than < 0:
        return _err("--older-than must be >= 0")
    manager = _context_manager_for_tenant()
    removed = manager.prune_before(args.older_than, args.type)
    print(f"pruned {removed} message(s) older than {args.older_than} days")
    return 0


def cmd_context_clear(args: argparse.Namespace) -> int:
    """Clear all context data for the tenant (confirmation required without --yes)."""
    if not args.yes:
        try:
            answer = input("Are you sure? This deletes ALL context data for this tenant. [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted — nothing deleted (pass --yes to skip confirmation)", file=sys.stderr)
            return 1
    manager = _context_manager_for_tenant()
    before = len(manager.messages)
    manager.clear()
    print(f"cleared {before} message(s)")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    """Add / list / execute tasks (JSON-backed, tenant-scoped, #137).

    - ``riks task <goal>``               -> queue (prints queued id)
    - ``riks task <goal> --execute``     -> queue + execute sync (result stdout)
    - ``riks task <goal> --timeout <s>`` -> sync execute with a hard timeout
    - ``riks task --list``               -> list queued tasks
    - ``riks task <id> --status``        -> query one task's status/result
    Exit codes (--execute): 0 success, 1 failure, 2 timeout.
    """
    if args.list:
        queue = TaskQueue()
        tasks = queue.list()
        if not tasks:
            print("task queue is empty")
            return 0
        for t in tasks:
            owner = f" [{t.owner_tenant}]" if t.owner_tenant else ""
            extra = f"\tresult={t.result!r}" if t.result is not None else ""
            print(f"{t.id}\t{t.status}\t{t.goal}{owner}{extra}")
        return 0

    # --status <id>: query a single task (tenant-scoped).
    if getattr(args, "status", None):
        queue = TaskQueue()
        tenant = os.environ.get("RIKS_TENANT_ID", "").strip()
        task = queue.get(args.status)
        if task is None:
            return _err(f"task not found: {args.status}")
        if task.owner_tenant and tenant and task.owner_tenant != tenant:
            return _err(
                f"access denied: task {args.status} belongs to tenant "
                f"'{task.owner_tenant}', not '{tenant}'"
            )
        print(f"{task.id}\t{task.status}\t{task.goal}")
        if task.result is not None:
            print(f"result: {task.result}")
        return 0

    if not args.goal:
        return _err("task goal is required (or use --list / --status <id>)")

    queue = TaskQueue()
    task = queue.add(args.goal.strip())
    print(f"task queued: {task.id} ({task.status})")

    if not getattr(args, "execute", False):
        return 0

    # --- Sync execution (#137) ---
    from riks_context_engine.tools import (
        ToolExecutionError,
        build_default_registry,
        execute_goal,
    )

    # Tenant isolation: the executing tenant must own the task.
    tenant = os.environ.get("RIKS_TENANT_ID", "").strip()
    if task.owner_tenant and tenant and task.owner_tenant != tenant:
        queue.mark(task.id, "failed", "access denied: cross-tenant execution")
        _err(f"access denied: task {task.id} belongs to tenant '{task.owner_tenant}'")
        return 1

    queue.mark(task.id, "running")
    timeout = args.timeout if getattr(args, "timeout", None) else None
    try:
        outcome = execute_goal(task.goal, build_default_registry(), timeout=timeout)
    except ToolExecutionError as exc:
        queue.mark(task.id, "failed", str(exc))
        _err(f"execution failed: {exc}")
        return 1

    if outcome.timed_out:
        queue.mark(task.id, "timeout", "execution timed out")
        print(f"timeout after {timeout}s: task {task.id}", file=sys.stderr)
        return 2

    queue.mark(task.id, "done", outcome.result)
    print(outcome.result)
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    """Reflect on a session: real analysis + lesson persistence to the store."""
    from riks_context_engine.memory.semantic import SemanticMemory
    from riks_context_engine.reflection.analyzer import ReflectionAnalyzer

    data_dir = os.environ.get("RIKS_DATA_DIR", "data")
    tenant = os.environ.get("RIKS_TENANT_ID", "").strip()
    sem_path, epi_path, proc_path = _memory_store_paths()
    semantic = SemanticMemory(db_path=sem_path)
    lessons_path = (
        os.path.join(data_dir, "tenants", tenant, "lessons.json")
        if tenant
        else os.path.join(data_dir, "lessons.json")
    )
    analyzer = ReflectionAnalyzer(
        semantic_memory=semantic,
        storage_path=lessons_path,
        llm_base_url=os.environ.get("OLLAMA_BASE_URL"),
        llm_model=os.environ.get("OLLAMA_MODEL"),
    )

    # Collect conversation for the session: explicit transcript file, or the
    # persisted context window content (real store, not a mock).
    conversation: list[dict[str, str]] = []
    if args.transcript:
        try:
            raw = json.loads(Path(args.transcript).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return _err(f"cannot read transcript {args.transcript}: {exc}")
        if not isinstance(raw, list) or not all(isinstance(m, dict) for m in raw):
            return _err("transcript must be a JSON array of {role, content} objects")
        conversation = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in raw
        ]
    else:
        manager = _context_manager_for_tenant()
        conversation = [{"role": m.role, "content": m.content} for m in manager.messages]

    if not conversation:
        return _err(
            f"no data to reflect on for session {args.session} (context window empty and no --transcript given)"
        )

    report = analyzer.analyze(interaction_id=f"session_{args.session}", conversation=conversation)
    analyzer.save()

    print(f"reflection: session={args.session} source={report.source}")
    if report.went_well:
        print(f"went_well: {len(report.went_well)} item(s)")
    if report.went_wrong:
        print(f"went_wrong: {len(report.went_wrong)} item(s)")
    if report.lessons:
        print(f"lessons: {len(report.lessons)}")
        for lesson in report.lessons:
            print(f"  [{lesson.severity}] {lesson.category}: {lesson.lesson_text}")
    return 0


def cmd_doctor() -> int:
    """Check data integrity; exit 0 if clean, exit 1 if corrupt."""
    data_dir = os.environ.get("RIKS_DATA_DIR", "data")

    from riks_context_engine.integrity import check_data_integrity

    problems = check_data_integrity(data_dir)

    if not problems:
        print("all data files OK")
        return 0

    print(f"found {len(problems)} problem(s):\n", file=sys.stderr)
    for p in problems:
        print(f"  [{p.kind}] {p.path}: {p.detail}", file=sys.stderr)

    backup_dir = Path(data_dir) / "backups"
    if backup_dir.is_dir():
        snapshots = sorted(
            [d for d in backup_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if snapshots:
            print(
                f"\nhint: latest backup available at {snapshots[0]}",
                file=sys.stderr,
            )
    return 1


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
    ctx.add_argument(
        "--type", type=str, default=None, help="prune: role filter (user/assistant/system)"
    )
    ctx.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="DAYS",
        help="prune: remove messages older than N days",
    )
    ctx.add_argument("--yes", action="store_true", help="clear: skip confirmation prompt")

    # Task commands
    task = sub.add_parser("task", help="Task operations")
    task.add_argument("goal", type=str, nargs="?", default=None, help="Goal to queue/execute")
    task.add_argument("--list", action="store_true", help="List queued tasks")
    task.add_argument(
        "--execute",
        action="store_true",
        help="Execute the task synchronously (result to stdout)",
    )
    task.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Hard timeout in seconds for sync execution",
    )
    task.add_argument(
        "--status",
        type=str,
        default=None,
        help="Query the status/result of a task by id",
    )

    # Reflection commands
    refl = sub.add_parser("reflect", help="Self-reflection")
    refl.add_argument("--session", type=str, required=True, help="Session ID to reflect on")
    refl.add_argument(
        "--transcript",
        type=str,
        default=None,
        help="Path to JSON transcript ([{role, content}, ...]); falls back to context window content",
    )

    # Doctor command
    sub.add_parser("doctor", help="Check data integrity")

    return parser


def _parse_known(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    """Parse CLI args; extra positionals (content text / search term) land in extras."""
    parser = _build_parser()
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, extras = _parse_known(argv)

    if args.version:
        from riks_context_engine import __version__

        print(f"riks-context-engine {__version__}")
        return 0

    if args.command is None:
        _build_parser().print_help()
        return 1

    # All commands are implemented against the real stores (#124).
    if args.command == "memory":
        text = extras[0] if extras else None
        if args.action == "add":
            return cmd_memory_add(args, text, extras)
        if args.action == "query":
            return cmd_memory_query(args, text)
        if args.action == "stats":
            return _err(
                "not implemented yet: riks memory stats (use context stats / riks context stats)"
            )
        return 1

    if extras:
        print(f"error: unexpected argument(s): {' '.join(extras)}", file=sys.stderr)
        return 2

    if args.command == "context":
        if args.action == "stats":
            return cmd_context_stats()
        if args.action == "prune":
            return cmd_context_prune(args)
        if args.action == "clear":
            return cmd_context_clear(args)

    if args.command == "task":
        return cmd_task(args)

    if args.command == "reflect":
        return cmd_reflect(args)

    if args.command == "doctor":
        return cmd_doctor()

    print(f"not implemented yet: riks {args.command} {getattr(args, 'action', '') or ''}".strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
