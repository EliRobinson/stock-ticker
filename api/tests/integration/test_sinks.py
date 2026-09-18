"""`upsert_quotes` (reliability review, provider seams) against a real,
migrated Postgres. See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.providers import ProviderQuote
from stockticker.ingest.sinks import upsert_quotes


async def test_upsert_quotes_inserts_and_then_keeps_the_newer_observation(
    app_writer_engine: AsyncEngine,
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    symbol = f"T{uuid.uuid4().hex[:6].upper()}"
    older = datetime.now(UTC) - timedelta(minutes=1)
    newer = datetime.now(UTC)

    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test')"),
            {"cik": cik},
        )
        await conn.execute(
            text(
                "INSERT INTO listings (symbol, cik, is_primary, is_active) VALUES (:symbol, :cik, true, true)"
            ),
            {"symbol": symbol, "cik": cik},
        )
        await conn.commit()

        written = await upsert_quotes(
            conn, [ProviderQuote(symbol=symbol, price=Decimal("10.00"), observed_at=older, feed="iex")]
        )
        await conn.commit()
        assert written == 1

        # An older observation must not overwrite the newer one.
        written = await upsert_quotes(
            conn,
            [ProviderQuote(symbol=symbol, price=Decimal("1.00"), observed_at=older, feed="iex")],
        )
        await conn.commit()
        assert written == 0

        written = await upsert_quotes(
            conn, [ProviderQuote(symbol=symbol, price=Decimal("11.00"), observed_at=newer, feed="iex")]
        )
        await conn.commit()
        assert written == 1

        row = (
            await conn.execute(
                text("SELECT price, observed_at FROM quotes WHERE symbol = :symbol"), {"symbol": symbol}
            )
        ).one()
        assert row.price == Decimal("11.00")

        await conn.execute(text("DELETE FROM quotes WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def test_upsert_quotes_empty_list_writes_nothing(app_writer_engine: AsyncEngine) -> None:
    async with app_writer_engine.connect() as conn:
        assert await upsert_quotes(conn, []) == 0
