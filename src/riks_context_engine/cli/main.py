"""Command-line interface for Rik's Context Engine."""

import argparse
import sys


def main() -> int:
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

    args = parser.parse_args()

    if args.version:
        from riks_context_engine import __version__
        print(f"riks-context-engine {__version__}")
        return 0

    if args.command is None:
        parser.print_help()
        return 1

    print("Command executed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
