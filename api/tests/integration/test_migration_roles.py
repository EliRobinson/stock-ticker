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


async def test_ai_reader_cannot_call_set_config(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT set_config('default_transaction_read_only', 'off', false)"))


async def test_set_read_only_off_does_not_grant_ai_reader_a_write(ai_reader_engine: AsyncEngine) -> None:
    """`set_config()` is blocked (see above), but the plain `SET` statement
    is a different mechanism entirely and Postgres does not restrict it by
    default -- this succeeds. Documented, not silently assumed: it doesn't
    matter, because ai_reader independently has no DML grant on anything to
    escape *to*. The future SQL guard (a later issue) closes the vector at
    the application layer too, since it only ever parses and runs a single
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
