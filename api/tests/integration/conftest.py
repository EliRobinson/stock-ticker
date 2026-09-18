"""Fixtures for tests that need a real, migrated Postgres.

`db` is not published to the host (system design §8), so these tests must
run where `POSTGRES_HOST=db` resolves -- inside the compose network:

    docker compose up -d db api
    docker compose exec api uv run alembic upgrade head   # if not already applied
    docker compose exec api uv run pytest tests/integration

or, without a running `api` container:

    docker compose run --rm api uv run pytest tests/integration

Each fixture skips (rather than fails) if the role can't connect, so
`uv run pytest` from the host still runs the unit suite cleanly -- unless
`REQUIRE_DB=1` is set (the pre-push hook's api step sets it), in which case
an unreachable DB fails the test instead of skipping it: a push must not
silently pass its integration suite because the compose db wasn't up.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stockticker.config import get_settings


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
    message = f"Postgres not reachable as {role} -- see tests/integration/conftest.py."
    if _require_db():
        pytest.fail(f"{message} REQUIRE_DB=1 is set: run `docker compose up -d db` first.")
    pytest.skip(message)


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


@pytest_asyncio.fixture
async def superuser_engine() -> AsyncIterator[AsyncEngine]:
    """The bootstrap superuser (system design §3) -- only for tests that
    need privileges no app role has (e.g. probing what a role *can't* do
    from outside it). Prefer app_writer_engine/ai_reader_engine otherwise."""
    engine = await _connectable(get_settings().superuser_dsn)
    if engine is None:
        _unreachable("superuser")
        return
    yield engine
    await engine.dispose()
