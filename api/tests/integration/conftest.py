"""Fixtures for tests that need a real, migrated Postgres.

`db` is not published to the host (system design §8), so these tests must
run where `POSTGRES_HOST=db` resolves -- inside the compose network:

    docker compose up -d db api
    docker compose exec api uv run alembic upgrade head   # if not already applied
    docker compose exec api uv run pytest tests/integration

or, without a running `api` container:

    docker compose run --rm api uv run pytest tests/integration

Each fixture skips (rather than fails) if the role can't connect, so
`uv run pytest` from the host still runs the unit suite cleanly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stockticker.config import get_settings


async def _connectable(dsn: str) -> AsyncEngine | None:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        return None
    return engine


@pytest_asyncio.fixture
async def app_writer_engine() -> AsyncIterator[AsyncEngine]:
    engine = await _connectable(get_settings().app_writer_dsn)
    if engine is None:
        pytest.skip("Postgres not reachable as app_writer -- see tests/integration/conftest.py.")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def ai_reader_engine() -> AsyncIterator[AsyncEngine]:
    engine = await _connectable(get_settings().ai_reader_dsn)
    if engine is None:
        pytest.skip("Postgres not reachable as ai_reader -- see tests/integration/conftest.py.")
    yield engine
    await engine.dispose()
