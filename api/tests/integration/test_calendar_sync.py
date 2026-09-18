"""`calendar_sync` (system design §4; issue #4 review comment 2) against a
real, migrated Postgres. See tests/integration/conftest.py for how to run
these."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.alpaca.client import CalendarDay
from stockticker.ingest.common import HISTORY_START
from stockticker.ingest.jobs.calendar_sync import FETCH_HORIZON_DAYS, run_calendar_sync
from stockticker.timeutil import NY_TZ, today_ny


class _FakeCalendarClient:
    def __init__(self, days: list[CalendarDay]) -> None:
        self._days = days

    async def get_calendar(self, start: date, end: date) -> list[CalendarDay]:
        return [day for day in self._days if start <= day.trade_date <= end]


def _day(d: date) -> CalendarDay:
    return CalendarDay(
        trade_date=d,
        open_at=datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY_TZ),
        close_at=datetime(d.year, d.month, d.day, 16, 0, tzinfo=NY_TZ),
    )


def _full_coverage_days() -> list[CalendarDay]:
    today = today_ny()
    return [
        _day(today + timedelta(days=offset))
        for offset in range(-5, FETCH_HORIZON_DAYS)
        if (today + timedelta(days=offset)).weekday() < 5
    ] + [_day(HISTORY_START)]


async def _cleanup(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(
            text("DELETE FROM trading_days WHERE trade_date >= :start"), {"start": HISTORY_START}
        )
        await conn.commit()


async def _trading_day_row(engine: AsyncEngine, d: date) -> Row[Any] | None:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT open_at, close_at FROM trading_days WHERE trade_date = :d"), {"d": d}
            )
        ).first()


async def test_calendar_sync_upserts_future_rows(app_writer_engine: AsyncEngine) -> None:
    await _cleanup(app_writer_engine)
    try:
        result = await run_calendar_sync(app_writer_engine, _FakeCalendarClient(_full_coverage_days()))
        assert result.rows_written > 0

        row = await _trading_day_row(app_writer_engine, today_ny())
        assert row is not None
    finally:
        await _cleanup(app_writer_engine)


async def test_calendar_sync_fails_and_keeps_old_rows_when_coverage_is_short(
    app_writer_engine: AsyncEngine,
) -> None:
    await _cleanup(app_writer_engine)
    try:
        await run_calendar_sync(app_writer_engine, _FakeCalendarClient(_full_coverage_days()))

        today = today_ny()
        before = await _trading_day_row(app_writer_engine, today)
        assert before is not None

        short_days = [_day(today), _day(today + timedelta(days=5))]
        with pytest.raises(RuntimeError, match="covers"):
            await run_calendar_sync(app_writer_engine, _FakeCalendarClient(short_days))

        after = await _trading_day_row(app_writer_engine, today)
        assert after is not None
        assert after.close_at == before.close_at
    finally:
        await _cleanup(app_writer_engine)


async def test_calendar_sync_deletes_a_future_row_the_new_response_no_longer_has(
    app_writer_engine: AsyncEngine,
) -> None:
    await _cleanup(app_writer_engine)
    try:
        today = today_ny()
        cancelled_date = today + timedelta(days=200)
        first_pass = [*_full_coverage_days(), _day(cancelled_date)]
        await run_calendar_sync(app_writer_engine, _FakeCalendarClient(first_pass))

        assert await _trading_day_row(app_writer_engine, cancelled_date) is not None

        second_pass = [day for day in first_pass if day.trade_date != cancelled_date]
        await run_calendar_sync(app_writer_engine, _FakeCalendarClient(second_pass))

        assert await _trading_day_row(app_writer_engine, cancelled_date) is None
    finally:
        await _cleanup(app_writer_engine)
