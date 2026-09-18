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
        assert read_only == "on"
        assert statement_timeout == "5s"
