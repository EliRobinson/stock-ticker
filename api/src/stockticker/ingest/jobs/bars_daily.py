"""`bars_daily` (system design §4; issue #4 review comment 2): re-fetch the
last 5 Trading Days for every active Listing that has completed backfill
(diagrams.md §4: the `backfill_completed_at` gate -- a Listing `bars_backfill`
hasn't finished yet is skipped here), and upsert.

The drift check compares each fetched row's new `adj_close` against
whatever is already stored; a relative difference over 1e-6 queues a full
re-fetch for that symbol by inserting a `refetch_requests` row
(`reason='adj_drift'`, `from_date=2018-01-01`) *before* the 5-day window is
upserted (review comment 2) -- `bars_backfill` picks that row up on a later
run, resets the symbol's watermark to `from_date`, and rewrites its whole
series in one transaction, deleting the row afterward. This job never
rewrites history itself; it only ever touches the 5-day window and the
queue.

A bar whose `high`/`low` sits far outside its own `open`/`close` (a SIP bad
print, not a real move) is clamped before it's written -- see
`ingest.common.sanitize_bars`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.alpaca.bars import AlpacaBarSource
from stockticker.ingest.alpaca.client import require_alpaca_client
from stockticker.ingest.common import HISTORY_START, chunked, group_by_symbol, sanitize_bars
from stockticker.ingest.job import FailedItem, JobContext, JobResult, JobSkipped
from stockticker.ingest.providers import BarSource, ProviderBar
from stockticker.ingest.sinks import upsert_bars
from stockticker.timeutil import today_ny

BATCH_SIZE = 50
WINDOW_TRADING_DAYS = 5
DRIFT_RELATIVE_TOLERANCE = Decimal("0.000001")


def detect_drift(rows: list[ProviderBar], stored_adj_close: dict[date, Decimal]) -> bool:
    """True if any fetched row's new `adj_close` differs from the currently
    stored value by more than 1e-6, relative. A date with nothing stored yet
    (first time this window has bars) is not drift."""
    for row in rows:
        stored = stored_adj_close.get(row.trade_date)
        if not stored:
            continue
        if abs(stored - row.adj_close) / abs(stored) > DRIFT_RELATIVE_TOLERANCE:
            return True
    return False


async def bars_daily(ctx: JobContext) -> JobResult:
    client = require_alpaca_client()
    return await run_bars_daily(ctx.engine, AlpacaBarSource(client))


async def run_bars_daily(engine: AsyncEngine, source: BarSource) -> JobResult:
    async with engine.connect() as conn:
        window = await _recent_trading_days(conn, WINDOW_TRADING_DAYS)
        await conn.commit()
    if not window:
        raise JobSkipped("no Trading Days recorded yet")
    start, end = window[0], window[-1]

    async with engine.connect() as conn:
        symbols = await _backfilled_symbols(conn)
        await conn.commit()
    if not symbols:
        raise JobSkipped("no Listings have completed backfill yet")

    rows_written = 0
    failed_items: list[FailedItem] = []
    for batch in chunked(symbols, BATCH_SIZE):
        try:
            bars = await source.daily_bars(batch, start, end)
        except Exception as exc:  # noqa: BLE001 - the whole batch failed to fetch, retried next run
            failed_items.extend(FailedItem(key=symbol, error=str(exc)) for symbol in batch)
            continue

        bars, sanity_failed = sanitize_bars(bars)
        failed_items.extend(sanity_failed)
        grouped = group_by_symbol(bars)
        async with engine.connect() as conn:
            stored = await _stored_adj_closes(conn, batch, start, end)
            await conn.commit()
            for symbol in batch:
                rows = grouped.get(symbol, [])
                if not rows:
                    continue
                try:
                    if detect_drift(rows, stored.get(symbol, {})):
                        await _queue_drift_refetch(conn, symbol)
                    result = await upsert_bars(conn, rows)
                except Exception as exc:  # noqa: BLE001 - recorded as a per-item failure, run continues
                    await conn.rollback()
                    failed_items.append(FailedItem(key=symbol, error=str(exc)))
                else:
                    await conn.commit()
                    rows_written += result.rows_written
                    failed_items.extend(result.failed_items)

    return JobResult(rows_written=rows_written, failed_items=failed_items)


async def _recent_trading_days(conn: AsyncConnection, count: int) -> list[date]:
    """Read-only; executes on `conn` without committing -- `run_bars_daily`
    owns that decision (issue #26 item 3)."""
    rows = (
        await conn.execute(
            text(
                "SELECT trade_date FROM trading_days WHERE trade_date <= :today "
                "ORDER BY trade_date DESC LIMIT :n"
            ),
            {"today": today_ny(), "n": count},
        )
    ).all()
    return sorted(row.trade_date for row in rows)


async def _backfilled_symbols(conn: AsyncConnection) -> list[str]:
    """Read-only; executes without committing -- see `_recent_trading_days`."""
    rows = (
        await conn.execute(
            text(
                "SELECT symbol FROM listings WHERE is_active AND backfill_completed_at IS NOT NULL "
                "ORDER BY symbol"
            )
        )
    ).all()
    return [row.symbol for row in rows]


async def _stored_adj_closes(
    conn: AsyncConnection, symbols: list[str], start: date, end: date
) -> dict[str, dict[date, Decimal]]:
    """Read-only; executes without committing -- see `_recent_trading_days`."""
    stmt = text(
        "SELECT symbol, trade_date, adj_close FROM daily_bars "
        "WHERE symbol IN :symbols AND trade_date BETWEEN :start AND :end"
    ).bindparams(bindparam("symbols", expanding=True))
    rows = (await conn.execute(stmt, {"symbols": symbols, "start": start, "end": end})).all()
    result: dict[str, dict[date, Decimal]] = {}
    for row in rows:
        result.setdefault(row.symbol, {})[row.trade_date] = row.adj_close
    return result


async def _queue_drift_refetch(conn: AsyncConnection, symbol: str) -> None:
    """Executes without committing -- `run_bars_daily` commits this in the
    same transaction as the bar upsert it precedes, so the two land or roll
    back together (issue #26 item 3)."""
    await conn.execute(
        text(
            "INSERT INTO refetch_requests (symbol, reason, from_date) "
            "VALUES (:symbol, 'adj_drift', :from_date) "
            "ON CONFLICT (symbol, reason) DO UPDATE SET "
            "from_date = LEAST(refetch_requests.from_date, excluded.from_date), requested_at = now()"
        ),
        {"symbol": symbol, "from_date": HISTORY_START},
    )


__all__ = [
    "BATCH_SIZE",
    "DRIFT_RELATIVE_TOLERANCE",
    "WINDOW_TRADING_DAYS",
    "bars_daily",
    "detect_drift",
    "run_bars_daily",
]
