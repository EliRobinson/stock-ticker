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
from stockticker.ingest.sinks import EventRow, upsert_bars, upsert_events, upsert_quotes


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


async def test_upsert_quotes_two_item_batch_reports_the_real_row_count(
    app_writer_engine: AsyncEngine,
) -> None:
    # Regression test: the asyncpg dialect can't report `rowcount` for a
    # true multi-row "executemany" -- it comes back -1. A one-item batch
    # happened to look right, which is why this went unnoticed until a
    # batch of two or more rows was exercised.
    cik_a = f"9{uuid.uuid4().int % 10**8:08d}"
    cik_b = f"8{uuid.uuid4().int % 10**8:08d}"
    symbol_a = f"T{uuid.uuid4().hex[:6].upper()}"
    symbol_b = f"T{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(UTC)

    async with app_writer_engine.connect() as conn:
        await _seed_company_and_listing(conn, cik_a, symbol_a)
        await _seed_company_and_listing(conn, cik_b, symbol_b)
        await conn.commit()

        result = await upsert_quotes(
            conn,
            [
                ProviderQuote(symbol=symbol_a, price=Decimal("10.00"), observed_at=now, feed="iex"),
                ProviderQuote(symbol=symbol_b, price=Decimal("20.00"), observed_at=now, feed="iex"),
            ],
        )
        await conn.commit()
        assert result.rows_written == 2
        assert result.failed_items == []

        await _cleanup(conn, cik_a, symbol_a)
        await _cleanup(conn, cik_b, symbol_b)


async def test_upsert_bars_two_item_batch_reports_the_real_row_count(app_writer_engine: AsyncEngine) -> None:
    cik_a = f"9{uuid.uuid4().int % 10**8:08d}"
    cik_b = f"8{uuid.uuid4().int % 10**8:08d}"
    symbol_a = f"T{uuid.uuid4().hex[:6].upper()}"
    symbol_b = f"T{uuid.uuid4().hex[:6].upper()}"
    trade_date = date(2024, 1, 2)

    async with app_writer_engine.connect() as conn:
        await _seed_company_and_listing(conn, cik_a, symbol_a)
        await _seed_company_and_listing(conn, cik_b, symbol_b)
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

        bars = [
            ProviderBar(
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
            for symbol in (symbol_a, symbol_b)
        ]
        result = await upsert_bars(conn, bars)
        await conn.commit()
        assert result.rows_written == 2
        assert result.failed_items == []

        await _cleanup(conn, cik_a, symbol_a)
        await _cleanup(conn, cik_b, symbol_b)


async def test_upsert_events_two_item_batch_inserts_and_then_updates_on_conflict(
    app_writer_engine: AsyncEngine,
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    source = f"test-{uuid.uuid4().hex[:8]}"

    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test')"), {"cik": cik}
        )
        await conn.commit()

        events = [
            EventRow(
                cik=cik,
                symbol=symbol,
                event_date=date(2024, 1, 2),
                kind="filing_8k",
                title="First filing",
                details={"item": "5.02"},
                source=source,
                source_ref="ref-1",
            ),
            EventRow(
                cik=cik,
                symbol=symbol,
                event_date=date(2024, 1, 3),
                kind="filing_10q",
                title="Second filing",
                details={},
                source=source,
                source_ref="ref-2",
            ),
        ]
        result = await upsert_events(conn, events)
        await conn.commit()
        assert result.rows_written == 2
        assert result.failed_items == []

        # Re-ingesting the same source_ref with a new title updates in place.
        result = await upsert_events(
            conn,
            [
                EventRow(
                    cik=cik,
                    symbol=symbol,
                    event_date=date(2024, 1, 2),
                    kind="filing_8k",
                    title="First filing (amended)",
                    details={"item": "5.02", "amended": True},
                    source=source,
                    source_ref="ref-1",
                )
            ],
        )
        await conn.commit()
        assert result.rows_written == 1

        row = (
            await conn.execute(
                text("SELECT title FROM events WHERE source = :source AND source_ref = 'ref-1'"),
                {"source": source},
            )
        ).one()
        assert row.title == "First filing (amended)"

        await conn.execute(text("DELETE FROM events WHERE source = :source"), {"source": source})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def test_upsert_events_a_null_symbol_on_reingest_does_not_wipe_the_stored_one(
    app_writer_engine: AsyncEngine,
) -> None:
    """E.g. edgar_sync re-ingesting a filing for a Company that currently
    has no active primary Listing must not erase the symbol a previous
    ingest already recorded for that event."""
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    source = f"test-{uuid.uuid4().hex[:8]}"

    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test')"), {"cik": cik}
        )
        await conn.commit()

        await upsert_events(
            conn,
            [
                EventRow(
                    cik=cik,
                    symbol=symbol,
                    event_date=date(2024, 1, 2),
                    kind="filing_8k",
                    title="First filing",
                    details={},
                    source=source,
                    source_ref="ref-1",
                )
            ],
        )
        await conn.commit()

        await upsert_events(
            conn,
            [
                EventRow(
                    cik=cik,
                    symbol=None,
                    event_date=date(2024, 1, 2),
                    kind="filing_8k",
                    title="First filing (re-ingested, no active listing)",
                    details={},
                    source=source,
                    source_ref="ref-1",
                )
            ],
        )
        await conn.commit()

        row = (
            await conn.execute(
                text("SELECT symbol FROM events WHERE source = :source AND source_ref = 'ref-1'"),
                {"source": source},
            )
        ).one()
        assert row.symbol == symbol

        await conn.execute(text("DELETE FROM events WHERE source = :source"), {"source": source})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def test_upsert_events_unknown_cik_is_a_failed_item(app_writer_engine: AsyncEngine) -> None:
    unknown_cik = f"7{uuid.uuid4().int % 10**8:08d}"
    source = f"test-{uuid.uuid4().hex[:8]}"

    async with app_writer_engine.connect() as conn:
        result = await upsert_events(
            conn,
            [
                EventRow(
                    cik=unknown_cik,
                    symbol=None,
                    event_date=date(2024, 1, 2),
                    kind="filing_8k",
                    title="Orphan filing",
                    details={},
                    source=source,
                    source_ref="ref-orphan",
                )
            ],
        )
        assert result.rows_written == 0
        assert len(result.failed_items) == 1
        assert result.failed_items[0].key == f"{source}:ref-orphan"


async def test_upsert_events_empty_list_writes_nothing(app_writer_engine: AsyncEngine) -> None:
    async with app_writer_engine.connect() as conn:
        result = await upsert_events(conn, [])
        assert result.rows_written == 0
        assert result.failed_items == []
