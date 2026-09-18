"""Ensure the dedicated pytest database exists and is migrated.

Integration tests must never write to the compose app database
(`stockticker`). They use `stockticker_test` (issue #38). This script is
idempotent: safe to run before every pytest / pre-push gate.
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
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,)).fetchone()
        if exists is None:
            # Identifier from our env default / explicit override only — never
            # interpolate untrusted input here.
            conn.execute(f'CREATE DATABASE "{test_db}"')
            print(f"created database {test_db}", file=sys.stderr)
        else:
            print(f"database {test_db} already exists", file=sys.stderr)

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
