"""Async SQLAlchemy engines for the two roles the API and worker use.

`app_writer` has DML rights on the base tables (§3 of the system design).
`ai_reader` can only `SELECT` from the `ai.*` views, and is used solely by
the `/api/v1/chat` SQL guard — never for anything else.

One module-level engine per role *and purpose* (reliability review), not a
single factory keyed on caller-supplied pool-size kwargs: `api` gets
`get_api_app_writer_engine()` (5 + 5 overflow); `worker` gets
`get_worker_app_writer_engine()` (6 + 0) and its own tiny
`get_quotes_engine()` (pool_size=1) so `quotes_poll` never queues behind
the rest of the worker's jobs for a connection — freshness (N1) should
never be starved by a slow backfill batch. Every engine here gets
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


def _create_app_writer_engine(*, pool_size: int, max_overflow: int) -> AsyncEngine:
    return create_async_engine(
        get_settings().app_writer_dsn,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=POOL_ACQUIRE_TIMEOUT_SECONDS,
    )


@lru_cache
def get_api_app_writer_engine() -> AsyncEngine:
    return _create_app_writer_engine(pool_size=5, max_overflow=5)


@lru_cache
def get_worker_app_writer_engine() -> AsyncEngine:
    return _create_app_writer_engine(pool_size=6, max_overflow=0)


@lru_cache
def get_quotes_engine() -> AsyncEngine:
    """A dedicated single-connection app_writer engine for `quotes_poll`
    only (worker process). Never share this with other jobs."""
    return _create_app_writer_engine(pool_size=1, max_overflow=0)


@lru_cache
def get_ai_reader_engine() -> AsyncEngine:
    # The migration also caps ai_reader's server-side connection limit at 3
    # (§3); keep the client-side pool at or under that. Against the pytest
    # database, use pool_size=1 so integration fixtures can open their own
    # short-lived ai_reader engines without TooManyConnectionsError (#38).
    settings = get_settings()
    pool_size = 1 if settings.postgres_db.endswith("_test") else 3
    return create_async_engine(
        settings.ai_reader_dsn,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=POOL_ACQUIRE_TIMEOUT_SECONDS,
        # The /api/v1/chat SQL guard's executor runs DISCARD ALL before a
        # connection goes back to the pool (§6), which deallocates every
        # server-side prepared statement -- two separate client-side caches
        # don't know that and need disabling, or the next query (including
        # pool_pre_ping's) fails with "prepared statement ... does not
        # exist" (reproduced on PG17): asyncpg's own cache
        # (statement_cache_size, its native connect() kwarg) and
        # SQLAlchemy's own DBAPI-emulation-layer cache on top of asyncpg
        # (prepared_statement_cache_size -- a SQLAlchemy-recognized
        # connect_args key, popped before the rest reaches asyncpg.connect,
        # documented in sqlalchemy.dialects.postgresql.asyncpg). Trades a
        # little per-query overhead for correctness; this engine never runs
        # the same statement often enough for either cache to matter.
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )


async def get_app_writer_connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency: `Depends(get_app_writer_connection)`."""
    engine = get_api_app_writer_engine()
    async with engine.connect() as conn:
        yield conn


async def dispose_engines() -> None:
    for getter in (
        get_api_app_writer_engine,
        get_worker_app_writer_engine,
        get_quotes_engine,
        get_ai_reader_engine,
    ):
        if getter.cache_info().currsize:
            await getter().dispose()
            getter.cache_clear()
