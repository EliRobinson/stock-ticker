"""Ensure the dedicated pytest database exists and is migrated.

Integration tests must never write to the compose app database
(`stockticker`). They use `stockticker_test` (issue #38). This script is
idempotent: safe to run before every pytest / pre-push gate.

Each run drops and recreates `stockticker_test` so leftover Listings /
Companies from a prior suite cannot poison constituents_sync or
quotes_poll assertions that assume a clean universe.
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise SystemExit(f"{name} is required to ensure the test database")
    return value


def main() -> None:
    host = _env("POSTGRES_HOST", "db")
    port = int(_env("POSTGRES_PORT", "5432"))
    user = _env("POSTGRES_SUPERUSER", "postgres")
    password = _env("POSTGRES_SUPERUSER_PASSWORD")
    test_db = _env("POSTGRES_TEST_DB", "stockticker_test")

    with psycopg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        # Identifier from our env default / explicit override only — never
        # interpolate untrusted input here.
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (test_db,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
        conn.execute(f'CREATE DATABASE "{test_db}"')
        print(f"recreated database {test_db}", file=sys.stderr)

    env = os.environ.copy()
    env["POSTGRES_DB"] = test_db
    result = subprocess.run(
        ["uv", "run", "--no-sync", "alembic", "upgrade", "head"],
        check=False,
        env=env,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
