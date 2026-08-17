#!/usr/bin/env python3
"""Apply pending PostgreSQL migrations for riks-context-engine.

Usage:
    POSTGRES_DSN=postgresql://user:pass@host:5432/dbname python scripts/migrate_postgres.py

Migration files live in scripts/migrations/*.sql and are applied in
lexical order. Applied filenames are tracked in a schema_migrations
table, so re-running the script is a no-op once everything is applied.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def main() -> int:
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        print("POSTGRES_DSN environment variable is required", file=sys.stderr)
        return 1

    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        print("No migration files found in scripts/migrations/")
        return 0

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        for migration in migrations:
            if migration.name in applied:
                print(f"skip  {migration.name} (already applied)")
                continue
            with conn.cursor() as cur:
                cur.execute(migration.read_text())
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (migration.name,),
                )
            print(f"apply {migration.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
