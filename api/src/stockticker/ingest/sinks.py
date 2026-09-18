"""Writes `ProviderQuote`s to the `quotes` table (reliability review).

The spec's `upsert_quotes(session, quotes)` is `upsert_quotes(conn, quotes)`
here -- this codebase uses SQLAlchemy Core (`AsyncConnection`, see db.py)
throughout, not an ORM `Session`; the contract (upsert, newer-wins) is the
same either way."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.ingest.providers import ProviderQuote


async def upsert_quotes(conn: AsyncConnection, quotes: Sequence[ProviderQuote]) -> int:
    """Upsert each quote, keeping the existing row if it is already newer
    (system design §4, quotes_poll: "Upsert only if observed_at is newer").
    Returns the number of rows actually written."""
    if not quotes:
        return 0
    fetched_at = datetime.now(UTC)
    result = await conn.execute(
        text(
            "INSERT INTO quotes (symbol, price, observed_at, fetched_at, feed) "
            "VALUES (:symbol, :price, :observed_at, :fetched_at, :feed) "
            "ON CONFLICT (symbol) DO UPDATE SET "
            "price = excluded.price, observed_at = excluded.observed_at, "
            "fetched_at = excluded.fetched_at, feed = excluded.feed "
            "WHERE quotes.observed_at < excluded.observed_at"
        ),
        [
            {
                "symbol": quote.symbol,
                "price": quote.price,
                "observed_at": quote.observed_at,
                "fetched_at": fetched_at,
                "feed": quote.feed,
            }
            for quote in quotes
        ],
    )
    return result.rowcount or 0
