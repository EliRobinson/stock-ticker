"""Asserts `ai_reader`'s privileges match §3 of the system design exactly:
it can SELECT the `ai.*` views (and call `ai.returns_between`), and nothing
else -- no base tables, no writes, no advisory locks, no `pg_sleep`.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

AI_VIEWS = [
    "companies",
    "listings",
    "trading_days",
    "daily_prices",
    "market_caps",
    "events",
    "notes",
    "quotes",
]


async def test_ai_reader_cannot_select_base_tables(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT * FROM public.companies LIMIT 1"))


async def test_ai_reader_cannot_write(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(
                text(
                    "INSERT INTO ai.notes (start_date, end_date, body) "
                    "VALUES (current_date, current_date, 'x')"
                )
            )


async def test_ai_reader_cannot_call_pg_advisory_lock(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT pg_try_advisory_lock(1)"))


async def test_ai_reader_cannot_call_pg_sleep(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT pg_sleep(0.01)"))


@pytest.mark.parametrize("view", AI_VIEWS)
async def test_ai_reader_can_select_every_ai_view(ai_reader_engine: AsyncEngine, view: str) -> None:
    async with ai_reader_engine.connect() as conn:
        result = await conn.execute(text(f"SELECT * FROM ai.{view} LIMIT 1"))
        result.all()


async def test_ai_reader_can_call_returns_between(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM ai.returns_between(date '2018-01-01', date '2018-06-01')")
        )
        result.all()


async def test_ai_reader_session_settings_are_enforced(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        read_only = await conn.scalar(text("SHOW default_transaction_read_only"))
        statement_timeout = await conn.scalar(text("SHOW statement_timeout"))
        timezone = await conn.scalar(text("SHOW TimeZone"))
        assert read_only == "on"
        assert statement_timeout == "5s"
        assert timezone == "America/New_York"


async def test_ai_reader_can_call_today_ny(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        result = await conn.scalar(text("SELECT ai.today_ny()"))
        assert result is not None


async def test_ai_reader_cannot_create_a_temp_table(ai_reader_engine: AsyncEngine) -> None:
    """§4 hardening: TEMP is revoked from PUBLIC on the database and never
    granted back to ai_reader, so it cannot create a temp table to shadow a
    permanent one -- independent of, and prior to, whatever the SQL guard
    (a later issue) would reject."""
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("CREATE TEMP TABLE companies (cik text)"))


async def test_ai_reader_can_select_an_array_typed_column(ai_reader_engine: AsyncEngine) -> None:
    """`set_config` is granted to ai_reader (see the migration's comment at
    that GRANT block): asyncpg calls it internally, ahead of its own
    type-introspection query, for any array-typed bind parameter or
    result -- revoking it outright broke that for every asyncpg role, not
    just ai_reader (found during review, reproduced on PG17). A real
    date[] result exercises that exact introspection path."""
    async with ai_reader_engine.connect() as conn:
        result = await conn.scalar(text("SELECT array_agg(trade_date) FROM ai.trading_days"))
        assert result is None or isinstance(result, list)


async def test_set_read_only_off_does_not_grant_ai_reader_a_write(ai_reader_engine: AsyncEngine) -> None:
    """Postgres does not restrict the plain `SET` statement by default --
    this succeeds. Documented, not silently assumed: it doesn't matter,
    because ai_reader independently has no DML grant on anything to escape
    *to*. The future SQL guard (a later issue) closes the vector at the
    application layer too, since it only ever parses and runs a single
    SELECT -- a `SET` statement never reaches the database via `run_sql`."""
    async with ai_reader_engine.connect() as conn:
        await conn.execute(text("SET default_transaction_read_only = off"))
        read_only = await conn.scalar(text("SHOW default_transaction_read_only"))
        assert read_only == "off"  # the flag itself does flip...

        with pytest.raises(DBAPIError):
            # ...but there is still no INSERT grant anywhere for it to matter.
            await conn.execute(
                text(
                    "INSERT INTO ai.notes (start_date, end_date, body) "
                    "VALUES (current_date, current_date, 'x')"
                )
            )


async def test_ai_reader_cannot_persist_a_large_object_after_read_only_off(
    ai_reader_engine: AsyncEngine,
) -> None:
    """The actual escape found during review: large objects are their own
    privilege system, independent of table grants, so `BEGIN READ WRITE`
    (which overrides the session's read-only default per-transaction,
    regardless of any GUC) plus `lo_from_bytea` could persist arbitrary
    binary data even though ai_reader has no INSERT anywhere. Closed by
    revoking EXECUTE on every lo_*/loread/lowrite function from PUBLIC."""
    async with ai_reader_engine.connect() as conn:
        await conn.execute(text("SET default_transaction_read_only = off"))
        with pytest.raises(DBAPIError):
            await conn.execute(text("BEGIN READ WRITE"))
            await conn.execute(text("SELECT lo_from_bytea(0, 'x')"))


async def test_setting_statement_timeout_or_work_mem_does_not_escape_the_guard(
    ai_reader_engine: AsyncEngine,
) -> None:
    """Also found during review: `SET statement_timeout = 0` and
    `SET work_mem = '2GB'` both succeed for ai_reader -- Postgres has no
    mechanism to block a plain SET of a 'user'-context GUC by a
    non-superuser role (`REVOKE SET ON PARAMETER`, tried first, governs
    only `ALTER SYSTEM SET`; verified empirically, see the migration's
    comment at that block). Documented rather than silently left broken:
    it doesn't defeat the guard, because `DISCARD ALL` resets it before
    the connection returns to the pool, the guard's own
    `SET LOCAL statement_timeout='5s'` is transaction-scoped regardless of
    the session default, and a `SET` statement can never be submitted
    through `run_sql` in the first place (the guard requires exactly one
    parsed SELECT)."""
    async with ai_reader_engine.connect() as conn:
        await conn.execute(text("SET statement_timeout = 0"))
        await conn.execute(text("SET work_mem = '2GB'"))
        assert await conn.scalar(text("SHOW statement_timeout")) == "0"
        assert await conn.scalar(text("SHOW work_mem")) == "2GB"

        with pytest.raises(DBAPIError):
            await conn.execute(text("ALTER SYSTEM SET work_mem = '2GB'"))
