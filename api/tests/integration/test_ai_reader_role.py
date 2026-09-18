"""The `ai_reader` role is the real wall (system design §6, "SQL guard"): the
attacks `tests/unit/test_ai_guard.py` rejects must also fail when the guard
is bypassed and the SQL goes straight to the executor. See
tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stockticker.ai.executor import AiReaderExecutor, ToolError
from stockticker.ai.guard import GuardError, guard_sql
from stockticker.ai.prompt import _INSTRUCTIONS
from stockticker.ai.schema_prompt import read_schema_catalog
from stockticker.config import get_settings
from stockticker.db import POOL_ACQUIRE_TIMEOUT_SECONDS, dispose_engines, get_ai_reader_engine


@pytest_asyncio.fixture
async def executor(ai_reader_engine: AsyncEngine) -> AsyncIterator[AiReaderExecutor]:
    """The app's own ai_reader engine (`db.get_ai_reader_engine`). Requesting
    `ai_reader_engine` makes the test skip, or fail under REQUIRE_DB, when
    the role cannot connect. The engine is process-wide and each test has its
    own event loop, so it is disposed after every test."""
    yield AiReaderExecutor(get_ai_reader_engine())
    await dispose_engines()


ATTACKS = [
    "SELECT 1; DELETE FROM ai.notes",
    "SELECT 1; SELECT 2",
    "INSERT INTO ai.notes (start_date, end_date, body) VALUES (current_date, current_date, 'x')",
    "UPDATE ai.notes SET body = 'x'",
    "DELETE FROM ai.notes",
    "WITH gone AS (DELETE FROM ai.notes RETURNING *) SELECT * FROM gone",
    "SELECT * INTO stolen FROM ai.companies",
    "CREATE TABLE ai.x (a int)",
    "CREATE TEMP TABLE x AS SELECT 1",
    "SELECT * FROM ai.companies FOR UPDATE",
    "SELECT * FROM ai.notes FOR SHARE",
    "COPY (SELECT 1) TO '/tmp/stockticker-test'",
    "COPY ai.notes FROM '/etc/passwd'",
    "DO $$ BEGIN DELETE FROM notes; END $$",
    "SELECT query_to_xml('SELECT * FROM public.companies', true, true, '')",
    "SELECT pg_sleep(0.01)",
    "SELECT pg_advisory_lock(1)",
    "SELECT pg_try_advisory_xact_lock(1)",
    "SELECT dblink('host=127.0.0.1', 'SELECT 1')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('.')",
    "SELECT * FROM pg_catalog.pg_authid",
    "SELECT * FROM public.companies",
    "SELECT * FROM daily_bars",
    "SELECT * FROM shares_outstanding",
    "SELECT * FROM ai_usage",
    "WITH companies AS (SELECT * FROM public.companies) SELECT * FROM companies",
    "SELECT nextval('events_id_seq')",
    "ALTER ROLE ai_reader SET default_transaction_read_only = off",
    "LOCK TABLE ai.companies",
]


@pytest.mark.parametrize("sql", ATTACKS)
async def test_guard_rejects_the_attack(sql: str) -> None:
    with pytest.raises(GuardError):
        guard_sql(sql)


@pytest.mark.parametrize("sql", ATTACKS)
async def test_role_blocks_the_attack_with_the_guard_bypassed(executor: AiReaderExecutor, sql: str) -> None:
    with pytest.raises(ToolError):
        await executor.execute(sql)


async def test_writes_stay_blocked_after_attempts_to_leave_read_only(ai_reader_engine: AsyncEngine) -> None:
    async with ai_reader_engine.connect() as conn:
        raw = await conn.get_raw_connection()
        pg = raw.driver_connection
        assert pg is not None
        await pg.execute("BEGIN READ ONLY")
        await pg.execute("SET LOCAL statement_timeout = '5s'; SET LOCAL lock_timeout = '1s'")
        await pg.fetchval("SELECT count(*) FROM ai.companies")
        # Once the transaction has run a query, it cannot be switched back to read-write.
        for attempt in (
            "SET transaction_read_only = off",
            "SELECT set_config('transaction_read_only', 'off', true)",
        ):
            with pytest.raises(Exception, match="read-write|permission denied|set_config"):
                await pg.execute(attempt)
            await pg.execute("ROLLBACK")
            await pg.execute("BEGIN READ ONLY")
            await pg.fetchval("SELECT 1")
        with pytest.raises(Exception, match="read-only transaction|permission denied"):
            await pg.execute(
                "INSERT INTO ai.notes (start_date, end_date, body) VALUES (current_date, current_date, 'x')"
            )
        await pg.execute("ROLLBACK")

        # Even a transaction switched to read-write before its first query
        # cannot write: the role has no write privilege anywhere.
        await pg.execute("SET default_transaction_read_only = off")
        await pg.execute("BEGIN")
        await pg.execute("SET TRANSACTION READ WRITE")
        with pytest.raises(Exception, match="permission denied|cannot insert"):
            await pg.execute(
                "INSERT INTO ai.notes (start_date, end_date, body) VALUES (current_date, current_date, 'x')"
            )
        await pg.execute("ROLLBACK")
        await pg.execute("DISCARD ALL")
        await conn.invalidate()


async def test_executor_runs_a_guarded_query_with_column_types(executor: AiReaderExecutor) -> None:
    guarded = guard_sql("SELECT cik, name, date_added FROM ai.companies ORDER BY cik LIMIT 2")
    result = await executor.execute(guarded.wrapped_sql)
    assert [(c.name, c.type) for c in result.columns] == [
        ("cik", "text"),
        ("name", "text"),
        ("date_added", "date"),
    ]


async def test_executor_sql_error_is_a_tool_error_and_the_connection_is_reused(
    executor: AiReaderExecutor,
) -> None:
    with pytest.raises(ToolError, match="division by zero"):
        await executor.execute("SELECT 1 / 0")
    result = await executor.execute("SELECT 1 AS one")
    assert result.rows == [(1,)]


async def test_executor_discards_session_state_before_returning_the_connection(
    executor: AiReaderExecutor,
) -> None:
    await executor.execute(guard_sql("SELECT name FROM ai.companies").wrapped_sql)
    async with get_ai_reader_engine().connect() as conn:
        prepared = await conn.scalar(text("SELECT count(*) FROM pg_prepared_statements"))
    assert prepared == 0


async def test_every_limit_is_set_inside_the_transaction(executor: AiReaderExecutor) -> None:
    result = await executor.execute(
        "SELECT name, setting, unit FROM pg_settings WHERE name IN "
        "('transaction_read_only', 'statement_timeout', 'lock_timeout', 'temp_file_limit') ORDER BY name"
    )
    assert result.rows == [
        ("lock_timeout", "1000", "ms"),
        ("statement_timeout", "5000", "ms"),
        ("temp_file_limit", "65536", "kB"),
        ("transaction_read_only", "on", None),
    ]


# A set-returning function in the select list streams, so this runs until
# the statement timeout instead of spilling to a temp file.
ENDLESS = "SELECT sum(x) AS {marker} FROM (SELECT generate_series(1, 10000000000) AS x) s"


async def test_statement_timeout_is_a_tool_error(executor: AiReaderExecutor) -> None:
    with pytest.raises(ToolError, match="longer than 5s"):
        await executor.execute(ENDLESS.format(marker="total"))


async def test_temp_file_limit_is_a_tool_error(executor: AiReaderExecutor) -> None:
    with pytest.raises(ToolError, match="temp_file_limit"):
        await executor.execute("SELECT count(*) FROM generate_series(1, 10000000000)")


async def test_pool_acquire_timeout_is_a_tool_error(ai_reader_engine: AsyncEngine) -> None:
    # A one-connection pool, because ai_reader's CONNECTION LIMIT 3 would
    # otherwise be hit (the fixture's probe holds one) before the pool is.
    engine = create_async_engine(
        get_settings().ai_reader_dsn, pool_size=1, max_overflow=0, pool_timeout=POOL_ACQUIRE_TIMEOUT_SECONDS
    )
    try:
        executor = AiReaderExecutor(engine)
        async with engine.connect():
            with pytest.raises(ToolError, match="busy"):
                await executor.execute("SELECT 1")
    finally:
        await engine.dispose()


async def test_cancelling_the_caller_cancels_the_running_query(
    executor: AiReaderExecutor, ai_reader_engine: AsyncEngine
) -> None:
    marker = "cancel_probe_4242"
    task = asyncio.create_task(executor.execute(ENDLESS.format(marker=marker)))
    await asyncio.sleep(0.5)

    async def running() -> int:
        # A role sees its own sessions' query text in pg_stat_activity.
        async with ai_reader_engine.connect() as conn:
            count = await conn.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND query LIKE :q"),
                {"q": f"%{marker}%"},
            )
        return int(count or 0)

    assert await running() == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(20):
        if await running() == 0:
            break
        await asyncio.sleep(0.1)
    assert await running() == 0


async def test_schema_catalog_comes_from_the_view_comments(ai_reader_engine: AsyncEngine) -> None:
    catalog = await read_schema_catalog(ai_reader_engine)
    assert {
        "companies",
        "listings",
        "trading_days",
        "daily_prices",
        "market_caps",
        "events",
        "notes",
        "quotes",
    } <= (catalog.view_names)
    assert "returns_between" in {f.name for f in catalog.functions}
    rendered = catalog.render()
    assert "ai.companies -- One row per S&P 500 constituent company" in rendered
    assert "adj_close numeric" in rendered
    assert "ai.returns_between(d1 date, d2 date)" in rendered


async def test_ai_reader_cannot_read_base_tables_even_through_views_it_cannot_see(
    ai_reader_engine: AsyncEngine,
) -> None:
    async with ai_reader_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT * FROM public.notes"))


async def test_a_result_over_the_byte_cap_is_a_tool_error_not_an_out_of_memory(
    executor: AiReaderExecutor,
) -> None:
    # 20 rows of 1 MB each: over the 8 MB cap, so the cursor stops early.
    # (repeat() is off the guard's allow-list; this goes straight to the executor.)
    with pytest.raises(ToolError, match="larger than 8 MB"):
        await executor.execute("SELECT repeat('x', 1048576) AS big FROM generate_series(1, 20)")


@pytest.mark.parametrize(
    "attempt",
    [
        "SELECT set_config('statement_timeout', '0', true) AS s, sum(x) "
        "FROM (SELECT generate_series(1, 10000000000) AS x) q",
        "SELECT sum(x) FROM (SELECT generate_series(1, 10000000000) AS x) q "
        "WHERE set_config('statement_timeout', '0', true) IS NOT NULL",
    ],
)
async def test_a_query_cannot_raise_its_own_statement_timeout(
    executor: AiReaderExecutor, attempt: str
) -> None:
    with pytest.raises(ToolError, match="longer than 5s"):
        await executor.execute(attempt)


async def test_a_raised_setting_does_not_outlive_its_query(executor: AiReaderExecutor) -> None:
    for attempt in (
        "SET statement_timeout = 0",
        "SET work_mem = '2GB'",
        "SET default_transaction_read_only = off",
    ):
        with contextlib.suppress(ToolError):
            await executor.execute(attempt)
    result = await executor.execute(
        "SELECT name, setting FROM pg_settings WHERE name IN "
        "('statement_timeout', 'work_mem', 'transaction_read_only') ORDER BY name"
    )
    settings = dict(result.rows)
    assert settings["statement_timeout"] == "5000"
    assert settings["transaction_read_only"] == "on"
    assert settings["work_mem"] != str(2 * 1024 * 1024)


PROMPT_EXAMPLES = re.findall(r"```sql\n(.*?)```", _INSTRUCTIONS, flags=re.DOTALL)


@pytest.mark.parametrize("sql", PROMPT_EXAMPLES)
async def test_every_prompt_example_passes_the_guard_and_runs(executor: AiReaderExecutor, sql: str) -> None:
    await executor.execute(guard_sql(sql).wrapped_sql)


async def test_today_ny_is_listed_and_callable(
    ai_reader_engine: AsyncEngine, executor: AiReaderExecutor
) -> None:
    catalog = await read_schema_catalog(ai_reader_engine)
    assert "today_ny" in {f.name for f in catalog.functions}
    result = await executor.execute(guard_sql("SELECT ai.today_ny() AS today").wrapped_sql)
    assert result.columns[0].type == "date"
