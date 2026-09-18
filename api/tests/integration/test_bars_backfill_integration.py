"""`bars_backfill` (system design §4) against a real, migrated Postgres:
the watermark resume across two runs, `first_bar_date`/`backfill_completed_at`,
and a `refetch_requests` row being served and deleted. See
tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.jobs.bars_backfill import (
    SymbolBackfillOutcome,
    SymbolBackfillPlan,
    _write_symbol,
    run_bars_backfill,
)
from stockticker.ingest.providers import ProviderBar
from stockticker.timeutil import NY_TZ


class _FakeBarSource:
    """Stands in for `AlpacaBarSource`: `providers.BarSource.daily_bars`
    already returns fully joined bars, one call, no `adjustment` param."""

    def __init__(self, bars: dict[str, list[ProviderBar]]) -> None:
        self._bars = bars

    async def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> list[ProviderBar]:
        return [
            bar for symbol in symbols for bar in self._bars.get(symbol, []) if start <= bar.trade_date <= end
        ]


def _bar(symbol: str, d: date, close: str) -> ProviderBar:
    return ProviderBar(
        symbol=symbol,
        trade_date=d,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=10,
        adj_close=Decimal(close),
        source="alpaca",
    )


async def _ensure_trading_day(conn: AsyncConnection, d: date) -> None:
    await conn.execute(
        text(
            "INSERT INTO trading_days (trade_date, open_at, close_at) VALUES (:d, :o, :c) "
            "ON CONFLICT (trade_date) DO NOTHING"
        ),
        {
            "d": d,
            "o": datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY_TZ),
            "c": datetime(d.year, d.month, d.day, 16, 0, tzinfo=NY_TZ),
        },
    )
    await conn.commit()


async def _make_listing(conn: AsyncConnection, symbol: str) -> str:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    await conn.execute(
        text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test', 'Test')"), {"cik": cik}
    )
    await conn.execute(
        text("INSERT INTO listings (symbol, cik, is_primary, is_active) VALUES (:symbol, :cik, true, true)"),
        {"symbol": symbol, "cik": cik},
    )
    await conn.commit()
    return cik


async def _cleanup(engine: AsyncEngine, symbol: str, cik: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("DELETE FROM refetch_requests WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(
            text("DELETE FROM ingest_watermarks WHERE job = 'bars_backfill' AND key = :symbol"),
            {"symbol": symbol},
        )
        await conn.execute(text("DELETE FROM daily_bars WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.execute(
            text("DELETE FROM trading_days WHERE trade_date IN ('2018-01-02', '2018-01-03', '2018-01-04')")
        )
        await conn.commit()


async def test_bars_backfill_resumes_from_its_stored_watermark(app_writer_engine: AsyncEngine) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
        for d in (date(2018, 1, 2), date(2018, 1, 3), date(2018, 1, 4)):
            await _ensure_trading_day(conn, d)
    try:
        all_bars = {
            symbol: [
                _bar(symbol, date(2018, 1, 2), "10"),
                _bar(symbol, date(2018, 1, 3), "11"),
                _bar(symbol, date(2018, 1, 4), "12"),
            ]
        }

        # First run only "sees" through 2018-01-03 -- simulate a partial
        # fetch window by giving the fake source just the first two bars.
        await run_bars_backfill(app_writer_engine, _FakeBarSource({symbol: all_bars[symbol][:2]}))

        async with app_writer_engine.connect() as conn:
            watermark = (
                await conn.execute(
                    text("SELECT value FROM ingest_watermarks WHERE job = 'bars_backfill' AND key = :s"),
                    {"s": symbol},
                )
            ).scalar_one()
            assert watermark == "2018-01-03"

            listing = (
                await conn.execute(
                    text("SELECT first_bar_date, backfill_completed_at FROM listings WHERE symbol = :s"),
                    {"s": symbol},
                )
            ).one()
            assert listing.first_bar_date == date(2018, 1, 2)
            assert listing.backfill_completed_at is None  # not caught up to "today" yet

        # Second run resumes from 2018-01-04, the day after the watermark --
        # exactly the one remaining bar the fake source has for this symbol.
        await run_bars_backfill(app_writer_engine, _FakeBarSource(all_bars))

        async with app_writer_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT trade_date FROM daily_bars WHERE symbol = :s ORDER BY trade_date"),
                    {"s": symbol},
                )
            ).all()
            assert [row.trade_date for row in rows] == [date(2018, 1, 2), date(2018, 1, 3), date(2018, 1, 4)]

            listing = (
                await conn.execute(
                    text("SELECT first_bar_date FROM listings WHERE symbol = :s"), {"s": symbol}
                )
            ).one()
            assert listing.first_bar_date == date(2018, 1, 2)  # unchanged from the first run
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_bars_backfill_serves_and_deletes_a_refetch_request(app_writer_engine: AsyncEngine) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
        await _ensure_trading_day(conn, date(2018, 1, 2))
        await conn.execute(
            text("UPDATE listings SET backfill_completed_at = now(), first_bar_date = :d WHERE symbol = :s"),
            {"s": symbol, "d": date(2018, 1, 2)},
        )
        await conn.execute(
            text(
                "INSERT INTO refetch_requests (symbol, reason, from_date) "
                "VALUES (:s, 'adj_drift', :from_date)"
            ),
            {"s": symbol, "from_date": date(2018, 1, 1)},
        )
        await conn.commit()
    try:
        rewritten = {symbol: [_bar(symbol, date(2018, 1, 2), "999.99")]}
        result = await run_bars_backfill(app_writer_engine, _FakeBarSource(rewritten))
        assert result.rows_written == 1

        async with app_writer_engine.connect() as conn:
            remaining = (
                await conn.execute(
                    text("SELECT 1 FROM refetch_requests WHERE symbol = :s AND reason = 'adj_drift'"),
                    {"s": symbol},
                )
            ).first()
            assert remaining is None

            adj_close = (
                await conn.execute(
                    text("SELECT adj_close FROM daily_bars WHERE symbol = :s AND trade_date = :d"),
                    {"s": symbol, "d": date(2018, 1, 2)},
                )
            ).scalar_one()
            assert adj_close == Decimal("999.990000")
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_bars_backfill_does_not_delete_a_refetch_row_queued_after_selection(
    app_writer_engine: AsyncEngine,
) -> None:
    """FIX-LATER item: a refetch row is only deleted if its `requested_at`
    is at or before the value read at selection time -- a fresh request
    that lands mid-batch (e.g. a second drift hit) must survive, not be
    silently deleted by the run that already had its own copy in flight."""
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
        await _ensure_trading_day(conn, date(2018, 1, 2))
        await conn.execute(
            text("INSERT INTO refetch_requests (symbol, reason, from_date) VALUES (:s, 'adj_drift', :d)"),
            {"s": symbol, "d": date(2018, 1, 1)},
        )
        await conn.commit()
        requested_at = (
            await conn.execute(
                text("SELECT requested_at FROM refetch_requests WHERE symbol = :s"), {"s": symbol}
            )
        ).scalar_one()
    try:
        stale_selected_at = requested_at - timedelta(seconds=1)
        plan = SymbolBackfillPlan(
            symbol=symbol,
            resume_from=date(2018, 1, 1),
            first_run=False,
            refetch_reasons=frozenset({"adj_drift"}),
            refetch_selected_at=stale_selected_at,
        )
        outcome = SymbolBackfillOutcome(symbol=symbol, rows=[], watermark=None, completed=False)

        async with app_writer_engine.connect() as conn:
            await _write_symbol(conn, plan, outcome)
            await conn.commit()

        async with app_writer_engine.connect() as conn:
            remaining = (
                await conn.execute(
                    text("SELECT 1 FROM refetch_requests WHERE symbol = :s AND reason = 'adj_drift'"),
                    {"s": symbol},
                )
            ).first()
            assert remaining is not None  # not deleted: it's newer than what we "read" at selection
    finally:
        await _cleanup(app_writer_engine, symbol, cik)
