"""Runs guarded SQL as `ai_reader` (system design §6, "SQL guard", step 5).

Every query gets its own read-only transaction with its limits set inside it,
so nothing depends on role-level settings:

    BEGIN READ ONLY
    SET LOCAL statement_timeout = '5s'
    SET LOCAL lock_timeout = '1s'
    SET LOCAL temp_file_limit = '64MB'      -- see `_apply_temp_file_limit`
    <query>
    ROLLBACK
    DISCARD ALL                             -- before the connection goes back

The query runs through asyncpg directly (the SQLAlchemy pool still owns the
connection, its 2 s acquire timeout, and pre-ping). If the calling task is
cancelled (the browser went away), asyncpg sends a cancel request for the
running statement, and the connection is invalidated instead of being
returned to the pool. It uses no temp tables, so `ai_reader` needs no TEMP.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol

import asyncpg
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.logging import get_logger

logger = get_logger(__name__)

STATEMENT_TIMEOUT = "5s"
LOCK_TIMEOUT = "1s"
TEMP_FILE_LIMIT = "64MB"
_TEMP_FILE_LIMIT_KB = 64 * 1024


class ToolError(Exception):
    """A failure the model should read and can often fix. `str()` is the message."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    """Postgres type name, e.g. `date`, `numeric`, `text`, `timestamptz`, `int8`."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[Column]
    rows: list[tuple[Any, ...]]


class SqlExecutor(Protocol):
    async def execute(self, sql: str) -> QueryResult: ...


class AiReaderExecutor:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._can_set_temp_file_limit: bool | None = None

    async def execute(self, sql: str) -> QueryResult:
        conn = await self._acquire()
        clean = False
        try:
            raw = await conn.get_raw_connection()
            pg = raw.driver_connection
            assert isinstance(pg, asyncpg.Connection)
            outcome = await self._run(pg, sql)
            clean = True
        finally:
            await asyncio.shield(self._release(conn, clean=clean))
        if isinstance(outcome, ToolError):
            raise outcome
        return outcome

    async def _acquire(self) -> AsyncConnection:
        try:
            return await self._engine.connect()
        except sa_exc.TimeoutError:
            raise ToolError(
                "The database is busy: no ai_reader connection was free within 2 s. Run the query again."
            ) from None
        except (sa_exc.DBAPIError, OSError) as error:
            logger.warning("ai_reader_connect_failed", error=str(error))
            raise ToolError("The database is not reachable. The query did not run.") from None

    async def _run(self, pg: asyncpg.Connection, sql: str) -> QueryResult | ToolError:
        """A ToolError is returned, not raised, once the transaction is rolled
        back and the session discarded, so the connection can go back to the
        pool. A cancellation or a broken connection raises straight through,
        and the caller invalidates the connection instead."""
        await pg.execute("BEGIN READ ONLY")
        outcome = await self._query(pg, sql)
        await pg.execute("ROLLBACK")
        await pg.execute("DISCARD ALL")
        return outcome

    async def _query(self, pg: asyncpg.Connection, sql: str) -> QueryResult | ToolError:
        await pg.execute(
            f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'; SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"
        )
        try:
            await self._apply_temp_file_limit(pg)
            statement = await pg.prepare(sql)
            records = await statement.fetch()
        except ToolError as error:
            return error
        except asyncpg.QueryCanceledError:
            return ToolError(
                f"The query ran longer than {STATEMENT_TIMEOUT} and was stopped. "
                "Filter by date or symbol, or aggregate, and try again."
            )
        except asyncpg.PostgresError as error:
            return ToolError(_describe_postgres_error(error))
        columns = [Column(name=a.name, type=a.type.name) for a in statement.get_attributes()]
        return QueryResult(columns=columns, rows=[tuple(record.values()) for record in records])

    async def _apply_temp_file_limit(self, pg: asyncpg.Connection) -> None:
        """`temp_file_limit` is superuser-only unless the role holds
        `SET ON PARAMETER`. Without that grant, the role cannot change it
        either (not even with `ALTER ROLE ... SET`), so the value in effect
        was set by a superuser; it is verified instead of set."""
        if self._can_set_temp_file_limit is None:
            self._can_set_temp_file_limit = bool(
                await pg.fetchval("SELECT has_parameter_privilege('temp_file_limit', 'SET')")
            )
        if self._can_set_temp_file_limit:
            await pg.execute(f"SET LOCAL temp_file_limit = '{TEMP_FILE_LIMIT}'")
            return
        current = await pg.fetchval("SHOW temp_file_limit")
        limit_kb = _parse_size_kb(str(current))
        if limit_kb is None or limit_kb > _TEMP_FILE_LIMIT_KB:
            logger.error("ai_reader_temp_file_limit_unsafe", temp_file_limit=current)
            raise ToolError("The database is not configured safely for AI queries. The query did not run.")

    async def _release(self, conn: AsyncConnection, *, clean: bool) -> None:
        try:
            if not clean:
                await conn.invalidate()
            await conn.close()
        except Exception as error:  # the connection is being discarded anyway
            logger.warning("ai_reader_release_failed", error=str(error))


_SIZE = re.compile(r"^(-?\d+)\s*(kB|MB|GB|TB)?$")
_SIZE_FACTORS_KB = {None: 1, "kB": 1, "MB": 1024, "GB": 1024**2, "TB": 1024**3}


def _parse_size_kb(value: str) -> int | None:
    """`SHOW temp_file_limit` -> kB. `-1` (unlimited) and anything
    unparseable return None."""
    match = _SIZE.match(value.strip())
    if match is None or match.group(1).startswith("-"):
        return None
    return int(match.group(1)) * _SIZE_FACTORS_KB[match.group(2)]


def _describe_postgres_error(error: asyncpg.PostgresError) -> str:
    message = getattr(error, "message", None) or str(error)
    parts = [f"SQL error: {message}"]
    detail = getattr(error, "detail", None)
    hint = getattr(error, "hint", None)
    if detail:
        parts.append(f"Detail: {detail}")
    if hint:
        parts.append(f"Hint: {hint}")
    return " ".join(parts)[:1000]
