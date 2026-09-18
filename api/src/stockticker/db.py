"""Async SQLAlchemy engines for the two roles the API and worker use.

`app_writer` has DML rights on the base tables (§3 of the system design).
`ai_reader` can only `SELECT` from the `ai.*` views, and is used solely by
the `/api/v1/chat` SQL guard — never for anything else.

Pool sizes are call-site specific (reliability review): the `api` process
wants `get_app_writer_engine()` at its default (5 + 5 overflow); the
`worker` process calls it with `pool_size=6, max_overflow=0` and gets its
own tiny `get_quotes_engine()` (pool_size=1) so `quotes_poll` never queues
behind the rest of the worker's jobs for a connection — freshness (N1)
should never be starved by a slow backfill batch. Every engine here gets
`pool_pre_ping=True` and a 2s acquire timeout (`pool_timeout`): a request
or job would rather fail fast than queue indefinitely for a connection.

Code rule: never hold a DB transaction open across an HTTP call (e.g. a
call to Anthropic or Alpaca) — acquire the connection, do the DB work,
release it, *then* make the outbound call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from stockticker.config import get_settings

POOL_ACQUIRE_TIMEOUT_SECONDS = 2


@lru_cache
def get_app_writer_engine(*, pool_size: int = 5, max_overflow: int = 5) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.app_writer_dsn,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=POOL_ACQUIRE_TIMEOUT_SECONDS,
    )


@lru_cache
def get_quotes_engine() -> AsyncEngine:
    """A dedicated single-connection app_writer engine for `quotes_poll`
    only (worker process). Never share this with other jobs."""
    settings = get_settings()
    return create_async_engine(
        settings.app_writer_dsn,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=POOL_ACQUIRE_TIMEOUT_SECONDS,
    )


@lru_cache
def get_ai_reader_engine() -> AsyncEngine:
    settings = get_settings()
    # The migration also caps ai_reader's server-side connection limit at 3
    # (§3); keep the client-side pool at or under that.
    return create_async_engine(
        settings.ai_reader_dsn,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=0,
        pool_timeout=POOL_ACQUIRE_TIMEOUT_SECONDS,
        # The /api/v1/chat SQL guard's executor runs DISCARD ALL before a
        # connection goes back to the pool (§6), which deallocates every
        # server-side prepared statement -- but asyncpg's own client-side
        # statement cache doesn't know that, and the next query (including
        # pool_pre_ping's) fails with "prepared statement ... does not
        # exist" (reproduced on PG17). Disabling asyncpg's cache trades a
        # little per-query overhead for correctness here; this engine never
        # runs the same statement often enough for the cache to matter.
        connect_args={"statement_cache_size": 0},
    )


async def get_app_writer_connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency: `Depends(get_app_writer_connection)`."""
    engine = get_app_writer_engine()
    async with engine.connect() as conn:
        yield conn


async def get_ai_reader_connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency for the `/api/v1/chat` SQL guard only."""
    engine = get_ai_reader_engine()
    async with engine.connect() as conn:
        yield conn


async def dispose_engines() -> None:
    await get_app_writer_engine().dispose()
    await get_ai_reader_engine().dispose()
    get_app_writer_engine.cache_clear()
    get_ai_reader_engine.cache_clear()
    if get_quotes_engine.cache_info().currsize:
        await get_quotes_engine().dispose()
        get_quotes_engine.cache_clear()
