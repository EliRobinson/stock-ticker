"""Writes `ProviderQuote`s and `ProviderBar`s to Postgres.

Both sinks validate against `listings` first, rather than sending the whole
batch to the database and hoping: an unknown symbol becomes one
`FailedItem`, not a foreign-key error that fails every row in the batch. A
per-row savepoint would also work, but costs one round trip per row; this
is one extra query for the whole batch."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.ingest.job import FailedItem, JobResult
from stockticker.ingest.providers import ProviderBar, ProviderQuote


async def _known_symbols(conn: AsyncConnection, symbols: Sequence[str]) -> set[str]:
    if not symbols:
        return set()
    rows = await conn.execute(
        text("SELECT symbol FROM listings WHERE symbol = ANY(:symbols)"), {"symbols": list(set(symbols))}
    )
    return {row.symbol for row in rows}


async def upsert_quotes(conn: AsyncConnection, quotes: Sequence[ProviderQuote]) -> JobResult:
    """Upsert each quote, keeping the existing row if it is already newer
    (system design §4, quotes_poll: "Upsert only if observed_at is newer")."""
    if not quotes:
        return JobResult()

    known = await _known_symbols(conn, [q.symbol for q in quotes])
    valid = [q for q in quotes if q.symbol in known]
    unknown = [q for q in quotes if q.symbol not in known]

    written = 0
    if valid:
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
                    "symbol": q.symbol,
                    "price": q.price,
                    "observed_at": q.observed_at,
                    "fetched_at": fetched_at,
                    "feed": q.feed,
                }
                for q in valid
            ],
        )
        written = result.rowcount or 0

    failed = [FailedItem(key=q.symbol, error="unknown symbol") for q in unknown]
    return JobResult(rows_written=written, failed_items=failed)


async def upsert_bars(conn: AsyncConnection, bars: Sequence[ProviderBar]) -> JobResult:
    """Upsert each bar. `daily_bars.trade_date` also references
    `trading_days`, so a date outside the calendar (`calendar_sync` hasn't
    run yet, or the source sent a non-Trading-Day) fails that row's insert;
    the caller sees it as an unexpected exception, not a per-item failure
    -- run `calendar_sync` before any `BarSource` call."""
    if not bars:
        return JobResult()

    known = await _known_symbols(conn, [b.symbol for b in bars])
    valid = [b for b in bars if b.symbol in known]
    unknown = [b for b in bars if b.symbol not in known]

    written = 0
    if valid:
        ingested_at = datetime.now(UTC)
        result = await conn.execute(
            text(
                "INSERT INTO daily_bars "
                "(symbol, trade_date, open, high, low, close, volume, adj_close, source, ingested_at) "
                "VALUES (:symbol, :trade_date, :open, :high, :low, :close, :volume, "
                ":adj_close, :source, :ingested_at) "
                "ON CONFLICT (symbol, trade_date) DO UPDATE SET "
                "open = excluded.open, high = excluded.high, low = excluded.low, close = excluded.close, "
                "volume = excluded.volume, adj_close = excluded.adj_close, source = excluded.source, "
                "ingested_at = excluded.ingested_at"
            ),
            [
                {
                    "symbol": b.symbol,
                    "trade_date": b.trade_date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "adj_close": b.adj_close,
                    "source": b.source,
                    "ingested_at": ingested_at,
                }
                for b in valid
            ],
        )
        written = result.rowcount or 0

    failed = [FailedItem(key=f"{b.symbol}:{b.trade_date}", error="unknown symbol") for b in unknown]
    return JobResult(rows_written=written, failed_items=failed)
