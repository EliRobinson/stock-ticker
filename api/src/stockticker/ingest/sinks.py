"""Writes `ProviderQuote`s, `ProviderBar`s, and `EventRow`s to Postgres.

Every sink validates against `listings` first, rather than sending the
whole batch to the database and hoping: an unknown symbol becomes one
`FailedItem`, not a foreign-key error that fails every row in the batch. A
per-row savepoint would also work, but costs one round trip per row; this
is one extra query for the whole batch.

Every insert is a single `unnest(...)`-based statement, one execute call
per batch, not a list of parameter dicts passed to `execute` (SQLAlchemy's
"executemany" path). The asyncpg dialect can't report `rowcount` for a
true executemany -- it comes back `-1` for every batch of two or more rows
(one-row batches happened to look right, which is why this went unnoticed
until a multi-row batch was tested). `unnest` turns the whole batch into
one ordinary statement, whose `rowcount` SQLAlchemy reports correctly."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.ingest.job import FailedItem, JobResult
from stockticker.ingest.providers import ProviderBar, ProviderQuote


@dataclass(slots=True, frozen=True)
class EventRow:
    """One row for `events`: a sourced, dated fact about a company (system
    design §4). `(source, source_ref)` is the natural key -- SEC accession
    number, Alpaca corporate-action id, or a Wikipedia revision id -- so
    the same event re-ingested is an update, not a duplicate."""

    cik: str
    symbol: str | None
    event_date: date
    kind: str
    title: str
    details: dict[str, object]
    source: str
    source_ref: str


async def _known_symbols(conn: AsyncConnection, symbols: Sequence[str]) -> set[str]:
    if not symbols:
        return set()
    rows = await conn.execute(
        text("SELECT symbol FROM listings WHERE symbol = ANY(:symbols)"), {"symbols": list(set(symbols))}
    )
    return {row.symbol for row in rows}


async def _known_ciks(conn: AsyncConnection, ciks: Sequence[str]) -> set[str]:
    if not ciks:
        return set()
    rows = await conn.execute(
        text("SELECT cik FROM companies WHERE cik = ANY(:ciks)"), {"ciks": list(set(ciks))}
    )
    return {row.cik for row in rows}


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
                "SELECT * FROM unnest("
                "CAST(:symbols AS text[]), CAST(:prices AS numeric[]), "
                "CAST(:observed_ats AS timestamptz[]), CAST(:fetched_ats AS timestamptz[]), "
                "CAST(:feeds AS text[])) "
                "AS t(symbol, price, observed_at, fetched_at, feed) "
                "ON CONFLICT (symbol) DO UPDATE SET "
                "price = excluded.price, observed_at = excluded.observed_at, "
                "fetched_at = excluded.fetched_at, feed = excluded.feed "
                "WHERE quotes.observed_at < excluded.observed_at"
            ),
            {
                "symbols": [q.symbol for q in valid],
                "prices": [q.price for q in valid],
                "observed_ats": [q.observed_at for q in valid],
                "fetched_ats": [fetched_at] * len(valid),
                "feeds": [q.feed for q in valid],
            },
        )
        written = result.rowcount or 0

    failed = [FailedItem(key=q.symbol, error="unknown symbol") for q in unknown]
    return JobResult(rows_written=written, failed_items=failed)


async def upsert_bars(conn: AsyncConnection, bars: Sequence[ProviderBar]) -> JobResult:
    """Upsert each bar. `daily_bars.trade_date` also references
    `trading_days`, so a date outside the calendar (`calendar_sync` hasn't
    run yet, or the source sent a non-Trading-Day) fails the whole
    statement with an unexpected exception, not a per-item failure -- run
    `calendar_sync` before any `BarSource` call."""
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
                "SELECT * FROM unnest("
                "CAST(:symbols AS text[]), CAST(:trade_dates AS date[]), CAST(:opens AS numeric[]), "
                "CAST(:highs AS numeric[]), CAST(:lows AS numeric[]), CAST(:closes AS numeric[]), "
                "CAST(:volumes AS bigint[]), CAST(:adj_closes AS numeric[]), "
                "CAST(:sources AS text[]), CAST(:ingested_ats AS timestamptz[])) "
                "AS t(symbol, trade_date, open, high, low, close, volume, adj_close, source, ingested_at) "
                "ON CONFLICT (symbol, trade_date) DO UPDATE SET "
                "open = excluded.open, high = excluded.high, low = excluded.low, close = excluded.close, "
                "volume = excluded.volume, adj_close = excluded.adj_close, source = excluded.source, "
                "ingested_at = excluded.ingested_at"
            ),
            {
                "symbols": [b.symbol for b in valid],
                "trade_dates": [b.trade_date for b in valid],
                "opens": [b.open for b in valid],
                "highs": [b.high for b in valid],
                "lows": [b.low for b in valid],
                "closes": [b.close for b in valid],
                "volumes": [b.volume for b in valid],
                "adj_closes": [b.adj_close for b in valid],
                "sources": [b.source for b in valid],
                "ingested_ats": [ingested_at] * len(valid),
            },
        )
        written = result.rowcount or 0

    failed = [FailedItem(key=f"{b.symbol}:{b.trade_date}", error="unknown symbol") for b in unknown]
    return JobResult(rows_written=written, failed_items=failed)


async def upsert_events(conn: AsyncConnection, events: Sequence[EventRow]) -> JobResult:
    """Upsert each event on its `(source, source_ref)` natural key. Used by
    `edgar_sync` (10-K/10-Q/8-K filings), `corporate_actions_sync` (splits,
    dividends, symbol changes, spin-offs), and the constituents job's
    index-membership events. Deduped Python-side on `(source, source_ref)`
    before the query -- `unnest` doesn't collapse duplicate rows within one
    statement, and Postgres rejects an `ON CONFLICT` upsert that would
    affect the same row twice in one command."""
    if not events:
        return JobResult()

    known = await _known_ciks(conn, [e.cik for e in events])
    valid_by_key: dict[tuple[str, str], EventRow] = {}
    unknown: list[EventRow] = []
    for event in events:
        if event.cik not in known:
            unknown.append(event)
            continue
        valid_by_key[(event.source, event.source_ref)] = event
    valid = list(valid_by_key.values())

    written = 0
    if valid:
        result = await conn.execute(
            text(
                "INSERT INTO events "
                "(cik, symbol, event_date, kind, title, details, source, source_ref) "
                "SELECT * FROM unnest("
                "CAST(:ciks AS text[]), CAST(:symbols AS text[]), CAST(:event_dates AS date[]), "
                "CAST(:kinds AS text[]), CAST(:titles AS text[]), CAST(:details AS jsonb[]), "
                "CAST(:sources AS text[]), CAST(:source_refs AS text[])) "
                "AS t(cik, symbol, event_date, kind, title, details, source, source_ref) "
                "ON CONFLICT (source, source_ref) DO UPDATE SET "
                "cik = excluded.cik, symbol = excluded.symbol, event_date = excluded.event_date, "
                "kind = excluded.kind, title = excluded.title, details = excluded.details"
            ),
            {
                "ciks": [e.cik for e in valid],
                "symbols": [e.symbol for e in valid],
                "event_dates": [e.event_date for e in valid],
                "kinds": [e.kind for e in valid],
                "titles": [e.title for e in valid],
                "details": [_to_jsonb_param(e.details) for e in valid],
                "sources": [e.source for e in valid],
                "source_refs": [e.source_ref for e in valid],
            },
        )
        written = result.rowcount or 0

    failed = [FailedItem(key=f"{e.source}:{e.source_ref}", error="unknown cik") for e in unknown]
    return JobResult(rows_written=written, failed_items=failed)


def _to_jsonb_param(value: dict[str, object]) -> str:
    return json.dumps(value, default=str)
