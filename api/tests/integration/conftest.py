"""Fixtures for tests that need a real, migrated Postgres.

`db` is not published to the host (system design §8), so these tests must
run where `POSTGRES_HOST=db` resolves -- inside the compose network:

    docker compose run --rm migrate   # or ensure_test_database.py
    docker compose run --rm --no-deps --entrypoint "" api \\
      sh -c "REQUIRE_DB=1 uv run --no-sync pytest tests/integration"

Every integration test forces `POSTGRES_DB` to the dedicated test database
(`stockticker_test` by default, overridable via `POSTGRES_TEST_DB`) so a
pytest run can never write fake `ai_usage` / ingest rows into the compose
app database (issue #38). Ensure that database exists and is migrated
before running under `REQUIRE_DB=1` -- the pre-push hook does this via
`api/scripts/ensure_test_database.py`.

Each fixture skips (rather than fails) if the role can't connect, so
`uv run pytest` from the host still runs the unit suite cleanly -- unless
`REQUIRE_DB=1` is set (the pre-push hook's api step sets it), in which case
an unreachable DB fails the test instead of skipping it: a push must not
silently pass its integration suite because the compose db wasn't up.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

# Pin the test database before any stockticker settings import can cache the
# compose app DB name. Unit tests that never connect are unaffected.
os.environ["POSTGRES_DB"] = os.environ.get("POSTGRES_TEST_DB", "stockticker_test")

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stockticker.api.app import app
from stockticker.config import get_settings

get_settings.cache_clear()


def _require_db() -> bool:
    return os.environ.get("REQUIRE_DB") == "1"


async def _connectable(dsn: URL) -> AsyncEngine | None:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        return None
    return engine


def _unreachable(role: str) -> None:
    db = get_settings().postgres_db
    message = (
        f"Postgres not reachable as {role} on database {db!r} -- "
        "see tests/integration/conftest.py."
    )
    if _require_db():
        pytest.fail(
            f"{message} REQUIRE_DB=1 is set: run `docker compose up -d db`, then "
            "`docker compose run --rm --no-deps --entrypoint \"\" api "
            "uv run --no-sync python scripts/ensure_test_database.py`."
        )
    pytest.skip(message)


@pytest.fixture(scope="session", autouse=True)
def _assert_test_database() -> Iterator[None]:
    """Refuse to run integration fixtures against the compose app DB."""
    settings = get_settings()
    expected = os.environ.get("POSTGRES_TEST_DB", "stockticker_test")
    if settings.postgres_db != expected:
        pytest.fail(
            f"integration tests must use POSTGRES_DB={expected!r}, "
            f"got {settings.postgres_db!r} (issue #38)"
        )
    if settings.postgres_db == "stockticker":
        pytest.fail("refusing to run integration tests against the app database 'stockticker'")
    yield


@pytest_asyncio.fixture
async def app_writer_engine() -> AsyncIterator[AsyncEngine]:
    engine = await _connectable(get_settings().app_writer_dsn)
    if engine is None:
        _unreachable("app_writer")
        return
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def ai_reader_engine() -> AsyncIterator[AsyncEngine]:
    engine = await _connectable(get_settings().ai_reader_dsn)
    if engine is None:
        _unreachable("ai_reader")
        return
    yield engine
    await engine.dispose()


# No superuser_engine fixture: the compose `api` service (where the
# pre-push gate's REQUIRE_DB=1 suite actually runs) has no
# POSTGRES_SUPERUSER_PASSWORD -- only `migrate` does, deliberately, so the
# app service never holds superuser credentials. A fixture here would
# `pytest.fail` under REQUIRE_DB=1 for anyone who added a test using it.
# Prefer app_writer_engine/ai_reader_engine; if a test genuinely needs
# superuser (e.g. probing what a role *can't* do from outside it), it
# needs a different, deliberate wiring, not a drop-in fixture.


@pytest.fixture(scope="session")
def api_client() -> Iterator[TestClient]:
    """One `TestClient` for the whole session (system design §5 API
    contract tests, `test_*_api.py`).

    `stockticker.db`'s engine getters are `@lru_cache`d at process scope, so
    the asyncpg connection pool they create on first use is bound to
    whichever event loop was running then. `TestClient` runs the ASGI app on
    its own dedicated background event loop for as long as the `with` block
    is open -- a *second* `TestClient(app)` (a fresh instance, its own new
    loop) reusing that already-bound pool raises "Future attached to a
    different loop". One client, opened once for the session, keeps every
    request on the same loop the engine was first created on.
    """
    get_settings.cache_clear()
    from stockticker.db import (
        get_ai_reader_engine,
        get_api_app_writer_engine,
        get_quotes_engine,
        get_worker_app_writer_engine,
    )

    for getter in (
        get_api_app_writer_engine,
        get_worker_app_writer_engine,
        get_quotes_engine,
        get_ai_reader_engine,
    ):
        getter.cache_clear()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client
