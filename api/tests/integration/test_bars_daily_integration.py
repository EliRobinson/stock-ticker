"""`bars_daily` (system design §4; issue #4 review comment 2) against a
real, migrated Postgres: the `backfill_completed_at` gate, and the drift
check inserting a `refetch_requests` row before the window is upserted. See
tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.jobs.bars_daily import run_bars_daily
from stockticker.ingest.providers import ProviderBar
from stockticker.timeutil import NY_TZ, today_ny


class _FakeBarSource:
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
        volume=5,
        adj_close=Decimal(close),
        source="alpaca",
    )


async def _make_listing(conn: AsyncConnection, symbol: str, *, backfilled: bool) -> str:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    await conn.execute(
        text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test', 'Test')"), {"cik": cik}
    )
    await conn.execute(
        text(
            "INSERT INTO listings (symbol, cik, is_primary, is_active, backfill_completed_at) "
            "VALUES (:symbol, :cik, true, true, :completed)"
        ),
        {"symbol": symbol, "cik": cik, "completed": datetime.now(NY_TZ) if backfilled else None},
    )
    await conn.commit()
    return cik


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


async def _cleanup(engine: AsyncEngine, symbol: str, cik: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("DELETE FROM refetch_requests WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM daily_bars WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def test_bars_daily_skips_a_listing_that_has_not_finished_backfill(
    app_writer_engine: AsyncEngine,
) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    control_symbol = f"T{uuid.uuid4().hex[:6].upper()}"  # backfilled, so the job has *something* to do
    today = today_ny()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol, backfilled=False)
        control_cik = await _make_listing(conn, control_symbol, backfilled=True)
        await _ensure_trading_day(conn, today)
    try:
        source = _FakeBarSource(
            {symbol: [_bar(symbol, today, "1")], control_symbol: [_bar(control_symbol, today, "2")]}
        )
        await run_bars_daily(app_writer_engine, source)

        async with app_writer_engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT 1 FROM daily_bars WHERE symbol = :s"), {"s": symbol})
            ).first()
            assert row is None

            control_row = (
                await conn.execute(text("SELECT 1 FROM daily_bars WHERE symbol = :s"), {"s": control_symbol})
            ).first()
            assert control_row is not None
    finally:
        await _cleanup(app_writer_engine, symbol, cik)
        await _cleanup(app_writer_engine, control_symbol, control_cik)


async def test_bars_daily_drift_check_queues_a_refetch_before_upserting(
    app_writer_engine: AsyncEngine,
) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    today = today_ny()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol, backfilled=True)
        await _ensure_trading_day(conn, today)
        await conn.execute(
            text(
                "INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, adj_close, "
                "source, ingested_at) VALUES (:s, :d, 100, 100, 100, 100, 1, 100, 'alpaca', now())"
            ),
            {"s": symbol, "d": today},
        )
        await conn.commit()
    try:
        source = _FakeBarSource({symbol: [_bar(symbol, today, "150")]})  # a big jump: real drift
        result = await run_bars_daily(app_writer_engine, source)
        assert result.rows_written == 1

        async with app_writer_engine.connect() as conn:
            refetch = (
                await conn.execute(
                    text("SELECT from_date FROM refetch_requests WHERE symbol = :s AND reason = 'adj_drift'"),
                    {"s": symbol},
                )
            ).first()
            assert refetch is not None
            assert refetch.from_date == date(2018, 1, 1)

            adj_close = (
                await conn.execute(
                    text("SELECT adj_close FROM daily_bars WHERE symbol = :s AND trade_date = :d"),
                    {"s": symbol, "d": today},
                )
            ).scalar_one()
            assert adj_close == Decimal("150.000000")
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_bars_daily_no_drift_when_adj_close_is_unchanged(app_writer_engine: AsyncEngine) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    today = today_ny()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol, backfilled=True)
        await _ensure_trading_day(conn, today)
        await conn.execute(
            text(
                "INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, adj_close, "
                "source, ingested_at) VALUES (:s, :d, 100, 100, 100, 100, 1, 100, 'alpaca', now())"
            ),
            {"s": symbol, "d": today},
        )
        await conn.commit()
    try:
        source = _FakeBarSource({symbol: [_bar(symbol, today, "100")]})
        await run_bars_daily(app_writer_engine, source)

        async with app_writer_engine.connect() as conn:
            refetch = (
                await conn.execute(
                    text("SELECT 1 FROM refetch_requests WHERE symbol = :s AND reason = 'adj_drift'"),
                    {"s": symbol},
                )
            ).first()
            assert refetch is None
    finally:
        await _cleanup(app_writer_engine, symbol, cik)
