# -*- coding: utf-8 -*-
"""Apply versioned PostgreSQL/PostGIS migrations."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.postgres import get_engine

MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "postgres"


def _statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def apply_migrations() -> list[str]:
    """Apply each unapplied SQL migration once, in filename order."""
    migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not migrations:
        raise FileNotFoundError(f"No PostgreSQL migrations in {MIGRATIONS_DIR}")

    applied: list[str] = []
    with get_engine().begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS ops"))
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ops.schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        for migration in migrations:
            version = migration.name
            exists = connection.execute(
                text(
                    "SELECT 1 FROM ops.schema_migrations "
                    "WHERE version = :version"
                ),
                {"version": version},
            ).scalar_one_or_none()
            if exists:
                continue
            for statement in _statements(migration.read_text(encoding="utf-8")):
                connection.execute(text(statement))
            connection.execute(
                text("INSERT INTO ops.schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )
            applied.append(version)
    return applied


def main() -> None:
    migrations = apply_migrations()
    if migrations:
        print("Applied PostgreSQL migrations: " + ", ".join(migrations))
    else:
        print("PostgreSQL schemas and tables are already up to date.")


if __name__ == "__main__":
    main()
