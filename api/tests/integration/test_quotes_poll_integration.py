"""`quotes_poll` (system design §4) against a real, migrated Postgres:
market-closed skip, and that the upsert ordering (newer `observed_at` wins)
still holds through this job's own path. `run_quotes_poll` takes the quotes
engine directly (system design: "uses the reserved 1-connection engine");
these tests pass `app_writer_engine` in that role so they run against a
normal test-scoped engine rather than `db.get_quotes_engine()`'s
process-level singleton. See tests/integration/conftest.py for how to run
these."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.job import JobSkipped
from stockticker.ingest.jobs.quotes_poll import run_quotes_poll
from stockticker.ingest.providers import ProviderQuote
from stockticker.models.status import MarketClock


class _FakeClock:
    def __init__(self, *, is_open: bool) -> None:
        self._is_open = is_open

    async def get_clock(self, *, use_cache: bool = True) -> MarketClock:
        now = datetime.now(UTC)
        return MarketClock(is_open=self._is_open, next_open=now, next_close=now)


class _FakeQuoteSource:
    def __init__(self, quotes: list[ProviderQuote]) -> None:
        self._quotes = quotes

    async def snapshot(self, symbols: Sequence[str]) -> list[ProviderQuote]:
        wanted = set(symbols)
        return [quote for quote in self._quotes if quote.symbol in wanted]

    def stream(self, symbols: Sequence[str]) -> AsyncIterator[ProviderQuote]:  # pragma: no cover - unused
        raise NotImplementedError


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
        await conn.execute(text("DELETE FROM quotes WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def _quote_price(engine: AsyncEngine, symbol: str) -> Decimal:
    async with engine.connect() as conn:
        price = (
            await conn.execute(text("SELECT price FROM quotes WHERE symbol = :s"), {"s": symbol})
        ).scalar_one()
        assert isinstance(price, Decimal)
        return price


async def test_quotes_poll_skips_when_market_is_closed(app_writer_engine: AsyncEngine) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        with pytest.raises(JobSkipped, match="closed"):
            await run_quotes_poll(app_writer_engine, _FakeClock(is_open=False), _FakeQuoteSource([]))
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_quotes_poll_upserts_through_the_given_quotes_engine(app_writer_engine: AsyncEngine) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        observed = datetime.now(UTC)
        quotes = _FakeQuoteSource(
            [ProviderQuote(symbol=symbol, price=Decimal("42.00"), observed_at=observed, feed="iex")]
        )
        result = await run_quotes_poll(app_writer_engine, _FakeClock(is_open=True), quotes)
        assert result.rows_written == 1

        assert await _quote_price(app_writer_engine, symbol) == Decimal("42.00")
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_quotes_poll_records_a_symbol_missing_a_trade_as_a_failed_item(
    app_writer_engine: AsyncEngine,
) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        result = await run_quotes_poll(app_writer_engine, _FakeClock(is_open=True), _FakeQuoteSource([]))
        assert result.rows_written == 0
        # Other integration tests may leave active Listings in the shared
        # pytest DB; this run must still record *this* symbol as failed.
        assert symbol in [item.key for item in result.failed_items]
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_quotes_poll_never_overwrites_a_newer_quote_with_an_older_one(
    app_writer_engine: AsyncEngine,
) -> None:
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        newer = datetime.now(UTC)
        older = newer - timedelta(minutes=5)

        await run_quotes_poll(
            app_writer_engine,
            _FakeClock(is_open=True),
            _FakeQuoteSource(
                [ProviderQuote(symbol=symbol, price=Decimal("10.00"), observed_at=newer, feed="iex")]
            ),
        )
        await run_quotes_poll(
            app_writer_engine,
            _FakeClock(is_open=True),
            _FakeQuoteSource(
                [ProviderQuote(symbol=symbol, price=Decimal("1.00"), observed_at=older, feed="iex")]
            ),
        )

        assert await _quote_price(app_writer_engine, symbol) == Decimal("10.00")
    finally:
        await _cleanup(app_writer_engine, symbol, cik)
