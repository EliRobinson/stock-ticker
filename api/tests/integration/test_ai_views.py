"""`ai.quotes.change_pct` (migration 0001): anchored on the quote's own NY
date, comparing against the *exact* previous Trading Day's close, with no
silent fallback to an older bar if that day's bar is missing. See
tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _seed_company_and_listing(app_writer_engine: AsyncEngine, cik: str, symbol: str) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test')"), {"cik": cik}
        )
        await conn.execute(
            text(
                "INSERT INTO listings (symbol, cik, is_primary, is_active) VALUES (:symbol, :cik, true, true)"
            ),
            {"symbol": symbol, "cik": cik},
        )
        await conn.commit()


async def _seed_trading_day(app_writer_engine: AsyncEngine, trade_date: date) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO trading_days (trade_date, open_at, close_at) "
                "VALUES (:d, :open_at, :close_at) ON CONFLICT DO NOTHING"
            ),
            {
                "d": trade_date,
                "open_at": datetime.combine(trade_date, time(14, 30), tzinfo=UTC),
                "close_at": datetime.combine(trade_date, time(21, 0), tzinfo=UTC),
            },
        )
        await conn.commit()


async def _seed_bar(app_writer_engine: AsyncEngine, symbol: str, trade_date: date, close: str) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, "
                "adj_close, source, ingested_at) "
                "VALUES (:symbol, :d, :close, :close, :close, :close, 100, :close, 'alpaca', now())"
            ),
            {"symbol": symbol, "d": trade_date, "close": close},
        )
        await conn.commit()


async def _seed_quote(app_writer_engine: AsyncEngine, symbol: str, price: str, observed_at: datetime) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO quotes (symbol, price, observed_at, fetched_at, feed) "
                "VALUES (:symbol, :price, :observed_at, now(), 'iex')"
            ),
            {"symbol": symbol, "price": price, "observed_at": observed_at},
        )
        await conn.commit()


async def _cleanup(app_writer_engine: AsyncEngine, cik: str, symbol: str) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(text("DELETE FROM quotes WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM daily_bars WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def _change_pct(ai_reader_engine: AsyncEngine, symbol: str) -> float | None:
    async with ai_reader_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT change_pct FROM ai.quotes WHERE symbol = :symbol"), {"symbol": symbol}
            )
        ).one()
        value: float | None = row.change_pct
        return value


async def test_change_pct_compares_against_the_exact_previous_trading_day(
    app_writer_engine: AsyncEngine, ai_reader_engine: AsyncEngine
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    await _seed_company_and_listing(app_writer_engine, cik, symbol)
    try:
        await _seed_trading_day(app_writer_engine, date(2024, 1, 2))
        await _seed_trading_day(app_writer_engine, date(2024, 1, 3))
        await _seed_bar(app_writer_engine, symbol, date(2024, 1, 2), "100.00")
        await _seed_quote(app_writer_engine, symbol, "110.00", datetime(2024, 1, 3, 15, 0, tzinfo=UTC))

        change_pct = await _change_pct(ai_reader_engine, symbol)
        assert change_pct is not None
        assert round(float(change_pct), 4) == 0.1
    finally:
        await _cleanup(app_writer_engine, cik, symbol)


async def test_change_pct_is_null_not_a_fallback_when_the_exact_prior_day_bar_is_missing(
    app_writer_engine: AsyncEngine, ai_reader_engine: AsyncEngine
) -> None:
    """A genuine ingest gap: the Trading Day immediately before the quote
    has no daily_bars row (only an older day does). change_pct must come
    back null, not silently compare against the older bar."""
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    await _seed_company_and_listing(app_writer_engine, cik, symbol)
    try:
        await _seed_trading_day(app_writer_engine, date(2024, 1, 2))
        await _seed_trading_day(app_writer_engine, date(2024, 1, 3))
        await _seed_trading_day(app_writer_engine, date(2024, 1, 4))
        await _seed_bar(app_writer_engine, symbol, date(2024, 1, 2), "100.00")
        # 2024-01-03 is a Trading Day with no bar -- the ingest gap.
        await _seed_quote(app_writer_engine, symbol, "110.00", datetime(2024, 1, 4, 15, 0, tzinfo=UTC))

        assert await _change_pct(ai_reader_engine, symbol) is None
    finally:
        await _cleanup(app_writer_engine, cik, symbol)


async def test_change_pct_is_null_before_any_trading_day_precedes_the_quote(
    app_writer_engine: AsyncEngine, ai_reader_engine: AsyncEngine
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    await _seed_company_and_listing(app_writer_engine, cik, symbol)
    try:
        await _seed_trading_day(app_writer_engine, date(2024, 1, 2))
        await _seed_quote(app_writer_engine, symbol, "50.00", datetime(2024, 1, 2, 13, 0, tzinfo=UTC))

        assert await _change_pct(ai_reader_engine, symbol) is None
    finally:
        await _cleanup(app_writer_engine, cik, symbol)
