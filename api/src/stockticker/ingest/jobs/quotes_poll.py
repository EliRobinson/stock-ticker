"""`quotes_poll` (system design §4): every 15s while the market is open,
Alpaca `/v2/stocks/snapshots` (`feed=iex`, batches of 100), upserting only a
newer `observed_at`. No retries -- the next 15s tick is the retry
(`AlpacaQuoteSource.snapshot` calls the client with `attempts=1`). Its
`JobSpec` sets `engine="quotes"` (`ingest/registry.py`), so both the
advisory lock and `ctx.engine`/`ctx.quotes_engine` are the small, dedicated
quotes engine (`db.get_quotes_engine`) -- never the pool the rest of the
worker's jobs share -- so freshness (N1) is never queued behind a slow
backfill batch, not even to take the lock. The market clock is cached ~60s
inside `AlpacaClient`, shared with `/status`'s own clock check.

`run_quotes_poll` takes the two provider seams directly (`ClockSource`,
`providers.QuoteSource`) rather than one Alpaca-shaped client -- the
`AlpacaQuoteSource(client)` wiring lives in the handler, not here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.alpaca.client import ClockSource, require_alpaca_client
from stockticker.ingest.alpaca.quotes import AlpacaQuoteSource
from stockticker.ingest.common import active_symbols, chunked
from stockticker.ingest.job import FailedItem, JobContext, JobResult, JobSkipped
from stockticker.ingest.providers import QuoteSource
from stockticker.ingest.sinks import upsert_quotes

BATCH_SIZE = 100


async def quotes_poll(ctx: JobContext) -> JobResult:
    client = require_alpaca_client()
    return await run_quotes_poll(ctx.quotes_engine, client, AlpacaQuoteSource(client))


async def run_quotes_poll(quotes_engine: AsyncEngine, clock: ClockSource, quotes: QuoteSource) -> JobResult:
    if not (await clock.get_clock()).is_open:
        raise JobSkipped("market is closed")

    async with quotes_engine.connect() as conn:
        symbols = await active_symbols(conn)
    if not symbols:
        raise JobSkipped("no active Listings")

    rows_written = 0
    failed_items: list[FailedItem] = []
    for batch in chunked(symbols, BATCH_SIZE):
        try:
            snapshot = await quotes.snapshot(batch)
        except Exception as exc:  # noqa: BLE001 - the whole batch failed, retried next tick
            failed_items.extend(FailedItem(key=symbol, error=str(exc)) for symbol in batch)
            continue

        found = {quote.symbol for quote in snapshot}
        failed_items.extend(
            FailedItem(key=symbol, error="no trade") for symbol in batch if symbol not in found
        )

        async with quotes_engine.connect() as conn:
            result = await upsert_quotes(conn, snapshot)
            await conn.commit()
        rows_written += result.rows_written
        failed_items.extend(result.failed_items)

    return JobResult(rows_written=rows_written, failed_items=failed_items)


__all__ = ["BATCH_SIZE", "quotes_poll", "run_quotes_poll"]
