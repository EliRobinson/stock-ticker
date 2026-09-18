"""`calendar_sync` (system design §4; issue #4 review comment 2): Alpaca
`/v2/calendar` from 2018-01-01 through a year of headroom past today. The
job fails -- keeping the existing rows -- if the response doesn't reach
today + 300 days, so a truncated response can never quietly erase future
Trading Days. On success, the future window (>= today) is replaced: every
returned future row is upserted, and any previously-stored future row the
response no longer has (an unscheduled closure) is deleted. Past rows are
only ever upserted, never deleted -- first run populates them from scratch,
later runs just correct in place.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.alpaca.client import CalendarSource, require_alpaca_client
from stockticker.ingest.common import HISTORY_START
from stockticker.ingest.job import JobContext, JobResult
from stockticker.timeutil import today_ny

FETCH_HORIZON_DAYS = 366
MIN_COVERAGE_DAYS = 300


async def calendar_sync(ctx: JobContext) -> JobResult:
    client = require_alpaca_client()
    return await run_calendar_sync(ctx.engine, client)


async def run_calendar_sync(engine: AsyncEngine, client: CalendarSource) -> JobResult:
    today = today_ny()
    end = today + timedelta(days=FETCH_HORIZON_DAYS)
    days = await client.get_calendar(HISTORY_START, end)
    if not days:
        raise RuntimeError("Alpaca returned no calendar rows")

    coverage_days = (max(day.trade_date for day in days) - today).days
    if coverage_days < MIN_COVERAGE_DAYS:
        raise RuntimeError(
            f"response covers {coverage_days} days past today, need at least {MIN_COVERAGE_DAYS}"
        )

    future_dates = [day.trade_date for day in days if day.trade_date >= today]
    delete_stmt = text(
        "DELETE FROM trading_days WHERE trade_date >= :today AND trade_date NOT IN :keep"
    ).bindparams(bindparam("keep", expanding=True))

    async with engine.connect() as conn:
        await conn.execute(delete_stmt, {"today": today, "keep": future_dates})
        result = await conn.execute(
            text(
                "INSERT INTO trading_days (trade_date, open_at, close_at) "
                "VALUES (:trade_date, :open_at, :close_at) "
                "ON CONFLICT (trade_date) DO UPDATE SET "
                "open_at = excluded.open_at, close_at = excluded.close_at"
            ),
            [
                {"trade_date": day.trade_date, "open_at": day.open_at, "close_at": day.close_at}
                for day in days
            ],
        )
        await conn.commit()
    return JobResult(rows_written=result.rowcount if result.rowcount and result.rowcount > 0 else len(days))
