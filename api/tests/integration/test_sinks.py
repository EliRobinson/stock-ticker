"""`upsert_quotes`/`upsert_bars` (system design §4, provider seams) against
a real, migrated Postgres. See tests/integration/conftest.py for how to run
these."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.providers import ProviderBar, ProviderQuote
from stockticker.ingest.sinks import upsert_bars, upsert_quotes


async def _seed_company_and_listing(conn: AsyncConnection, cik: str, symbol: str) -> None:
    await conn.execute(
        text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test')"), {"cik": cik}
    )
    await conn.execute(
        text("INSERT INTO listings (symbol, cik, is_primary, is_active) VALUES (:symbol, :cik, true, true)"),
        {"symbol": symbol, "cik": cik},
    )


async def _cleanup(conn: AsyncConnection, cik: str, symbol: str) -> None:
    await conn.execute(text("DELETE FROM daily_bars WHERE symbol = :symbol"), {"symbol": symbol})
    await conn.execute(text("DELETE FROM quotes WHERE symbol = :symbol"), {"symbol": symbol})
    await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
    await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
    await conn.commit()


async def test_upsert_quotes_inserts_and_then_keeps_the_newer_observation(
    app_writer_engine: AsyncEngine,
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    older = datetime.now(UTC) - timedelta(minutes=1)
    newer = datetime.now(UTC)

    async with app_writer_engine.connect() as conn:
        await _seed_company_and_listing(conn, cik, symbol)
        await conn.commit()

        result = await upsert_quotes(
            conn, [ProviderQuote(symbol=symbol, price=Decimal("10.00"), observed_at=older, feed="iex")]
        )
        await conn.commit()
        assert result.rows_written == 1
        assert result.failed_items == []

        # An older observation must not overwrite the newer one.
        result = await upsert_quotes(
            conn,
            [ProviderQuote(symbol=symbol, price=Decimal("1.00"), observed_at=older, feed="iex")],
        )
        await conn.commit()
        assert result.rows_written == 0

        result = await upsert_quotes(
            conn, [ProviderQuote(symbol=symbol, price=Decimal("11.00"), observed_at=newer, feed="iex")]
        )
        await conn.commit()
        assert result.rows_written == 1

        row = (
            await conn.execute(
                text("SELECT price, observed_at FROM quotes WHERE symbol = :symbol"), {"symbol": symbol}
            )
        ).one()
        assert row.price == Decimal("11.00")

        await _cleanup(conn, cik, symbol)


async def test_upsert_quotes_unknown_symbol_is_a_failed_item_not_a_lost_batch(
    app_writer_engine: AsyncEngine,
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    known_symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    unknown_symbol = f"Z{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(UTC)

    async with app_writer_engine.connect() as conn:
        await _seed_company_and_listing(conn, cik, known_symbol)
        await conn.commit()

        result = await upsert_quotes(
            conn,
            [
                ProviderQuote(symbol=known_symbol, price=Decimal("10.00"), observed_at=now, feed="iex"),
                ProviderQuote(symbol=unknown_symbol, price=Decimal("5.00"), observed_at=now, feed="iex"),
            ],
        )
        await conn.commit()

        assert result.rows_written == 1
        assert len(result.failed_items) == 1
        assert result.failed_items[0].key == unknown_symbol

        row = (
            await conn.execute(
                text("SELECT count(*) AS n FROM quotes WHERE symbol = :symbol"), {"symbol": known_symbol}
            )
        ).one()
        assert row.n == 1

        await _cleanup(conn, cik, known_symbol)


async def test_upsert_quotes_empty_list_writes_nothing(app_writer_engine: AsyncEngine) -> None:
    async with app_writer_engine.connect() as conn:
        result = await upsert_quotes(conn, [])
        assert result.rows_written == 0
        assert result.failed_items == []


async def test_upsert_bars_writes_joined_ohlcv_adj_close_and_source(app_writer_engine: AsyncEngine) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    trade_date = date(2024, 1, 2)  # a real Tuesday; trading_days is seeded below regardless

    async with app_writer_engine.connect() as conn:
        await _seed_company_and_listing(conn, cik, symbol)
        await conn.execute(
            text(
                "INSERT INTO trading_days (trade_date, open_at, close_at) "
                "VALUES (:d, :open_at, :close_at) ON CONFLICT DO NOTHING"
            ),
            {
                "d": trade_date,
                "open_at": datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
                "close_at": datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
            },
        )
        await conn.commit()

        bar = ProviderBar(
            symbol=symbol,
            trade_date=trade_date,
            open=Decimal("10.00"),
            high=Decimal("11.00"),
            low=Decimal("9.50"),
            close=Decimal("10.50"),
            volume=1_000,
            adj_close=Decimal("10.40"),
            source="alpaca",
        )
        result = await upsert_bars(conn, [bar])
        await conn.commit()
        assert result.rows_written == 1
        assert result.failed_items == []

        row = (
            await conn.execute(
                text("SELECT close, adj_close, source FROM daily_bars WHERE symbol = :symbol"),
                {"symbol": symbol},
            )
        ).one()
        assert row.close == Decimal("10.50")
        assert row.adj_close == Decimal("10.40")
        assert row.source == "alpaca"

        await _cleanup(conn, cik, symbol)


async def test_upsert_bars_empty_list_writes_nothing(app_writer_engine: AsyncEngine) -> None:
    async with app_writer_engine.connect() as conn:
        result = await upsert_bars(conn, [])
        assert result.rows_written == 0
        assert result.failed_items == []
