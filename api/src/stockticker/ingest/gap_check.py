"""`gap_check` (system design §4): find Trading Days with no Daily Bar and
queue them for `bars_backfill` through `refetch_requests` (reason `gap`).
This job never fetches bars itself.

Scope: active Listings with `backfill_completed_at` set. A gap is a Trading
Day between the Listing's `first_bar_date` and its latest bar with no bar.

One `refetch_requests` row per Listing covers all its gaps (`from_date` is
the earliest). `bars_backfill` deletes the row once its re-fetch commits, so
the attempt count has to outlive the row: it lives in `ingest_watermarks`
under this job (`attempts:{symbol}`).

Each night, for a Listing with open gaps:

- a pending (not accepted) row means `bars_backfill` has not served the last
  request yet, so the attempt is not counted again;
- otherwise the gaps survived a re-fetch: queue attempt n + 1;
- after `MAX_ATTEMPTS` re-fetches the gaps are accepted. The row stays with
  `accepted_at` set, so `/api/v1/status` can count accepted gaps, and the
  accepted dates are remembered (`accepted:{symbol}`) so they are not
  queued again. A later, new gap starts a fresh cycle on the same row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.job import JobContext, JobResult, JobSkipped
from stockticker.ingest.watermarks import delete_watermarks, read_watermarks, write_watermark
from stockticker.logging import get_logger

logger = get_logger(__name__)

JOB_NAME = "gap_check"
MAX_ATTEMPTS = 3
REASON = "gap"

_ATTEMPTS = "attempts:"
_ACCEPTED = "accepted:"

_LISTINGS_IN_SCOPE_SQL = text(
    "SELECT symbol FROM listings "
    "WHERE is_active AND backfill_completed_at IS NOT NULL AND first_bar_date IS NOT NULL "
    "ORDER BY symbol"
)

_GAPS_SQL = text(
    """
    SELECT l.symbol, array_agg(td.trade_date ORDER BY td.trade_date) AS gaps
    FROM listings l
    CROSS JOIN LATERAL (SELECT max(b.trade_date) AS last_bar FROM daily_bars b WHERE b.symbol = l.symbol) lb
    JOIN trading_days td ON td.trade_date >= l.first_bar_date AND td.trade_date <= lb.last_bar
    WHERE l.is_active AND l.backfill_completed_at IS NOT NULL AND l.first_bar_date IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM daily_bars b WHERE b.symbol = l.symbol AND b.trade_date = td.trade_date
      )
    GROUP BY l.symbol
    """
)


@dataclass(slots=True)
class GapCheckSummary:
    queued: int = 0
    waiting: int = 0
    accepted: int = 0


async def gap_check(ctx: JobContext) -> JobResult:
    return await run_gap_check(ctx.engine)


async def run_gap_check(engine: AsyncEngine) -> JobResult:
    async with engine.connect() as conn:
        summary = await check_gaps(conn)
        await conn.commit()
    logger.info("gap_check.done", queued=summary.queued, waiting=summary.waiting, accepted=summary.accepted)
    return JobResult(rows_written=summary.queued + summary.accepted)


async def check_gaps(conn: AsyncConnection) -> GapCheckSummary:
    """Queue or accept every open gap. Does not commit."""
    symbols = list((await conn.execute(_LISTINGS_IN_SCOPE_SQL)).scalars())
    if not symbols:
        raise JobSkipped("no active Listings with a completed backfill")
    gaps_by_symbol: dict[str, list[date]] = {
        row.symbol: list(row.gaps) for row in await conn.execute(_GAPS_SQL)
    }
    state = await _load_state(conn)
    pending = await _pending_requests(conn)

    summary = GapCheckSummary()
    no_gaps: list[str] = []
    for symbol in symbols:
        accepted = set(state.accepted.get(symbol, []))
        open_gaps = [day for day in gaps_by_symbol.get(symbol, []) if day not in accepted]
        if not open_gaps:
            no_gaps.append(symbol)
            continue
        if symbol in pending:
            await _widen_pending(conn, symbol, open_gaps[0])
            summary.waiting += 1
            continue
        attempts = state.attempts.get(symbol, 0)
        if attempts >= MAX_ATTEMPTS:
            await _accept(conn, symbol, open_gaps, sorted(accepted | set(open_gaps)))
            summary.accepted += 1
            logger.info("gap_check.accepted", symbol=symbol, gaps=[day.isoformat() for day in open_gaps])
            continue
        await _queue(conn, symbol, open_gaps[0], attempts + 1)
        summary.queued += 1
    await delete_watermarks(
        conn, JOB_NAME, [_ATTEMPTS + symbol for symbol in no_gaps if symbol in state.attempts]
    )
    return summary


@dataclass(slots=True)
class _State:
    attempts: dict[str, int]
    accepted: dict[str, list[date]]


async def _load_state(conn: AsyncConnection) -> _State:
    return _State(
        attempts={
            symbol: int(value) for symbol, value in (await read_watermarks(conn, JOB_NAME, _ATTEMPTS)).items()
        },
        accepted={
            symbol: [date.fromisoformat(day) for day in json.loads(value)]
            for symbol, value in (await read_watermarks(conn, JOB_NAME, _ACCEPTED)).items()
        },
    )


async def _pending_requests(conn: AsyncConnection) -> set[str]:
    """Rows `bars_backfill` has not tried yet. A row with `last_error` set was
    tried and failed, which counts as a served attempt."""
    result = await conn.execute(
        text(
            "SELECT symbol FROM refetch_requests "
            "WHERE reason = :reason AND accepted_at IS NULL AND last_error IS NULL"
        ),
        {"reason": REASON},
    )
    return set(result.scalars())


async def _queue(conn: AsyncConnection, symbol: str, from_date: date, attempts: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO refetch_requests (symbol, reason, from_date, attempts, requested_at) "
            "VALUES (:symbol, :reason, :from_date, :attempts, now()) "
            "ON CONFLICT (symbol, reason) DO UPDATE SET from_date = excluded.from_date, "
            "attempts = excluded.attempts, last_error = NULL, accepted_at = NULL, requested_at = now()"
        ),
        {"symbol": symbol, "reason": REASON, "from_date": from_date, "attempts": attempts},
    )
    await write_watermark(conn, JOB_NAME, _ATTEMPTS + symbol, str(attempts))


async def _widen_pending(conn: AsyncConnection, symbol: str, from_date: date) -> None:
    await conn.execute(
        text(
            "UPDATE refetch_requests SET from_date = LEAST(from_date, :from_date) "
            "WHERE symbol = :symbol AND reason = :reason AND accepted_at IS NULL"
        ),
        {"symbol": symbol, "reason": REASON, "from_date": from_date},
    )


async def _accept(
    conn: AsyncConnection, symbol: str, open_gaps: list[date], all_accepted: list[date]
) -> None:
    await conn.execute(
        text(
            "INSERT INTO refetch_requests (symbol, reason, from_date, attempts, accepted_at) "
            "VALUES (:symbol, :reason, :from_date, :attempts, now()) "
            "ON CONFLICT (symbol, reason) DO UPDATE SET from_date = excluded.from_date, "
            "attempts = excluded.attempts, accepted_at = now()"
        ),
        {"symbol": symbol, "reason": REASON, "from_date": open_gaps[0], "attempts": MAX_ATTEMPTS},
    )
    await write_watermark(
        conn, JOB_NAME, _ACCEPTED + symbol, json.dumps([day.isoformat() for day in all_accepted])
    )
    await delete_watermarks(conn, JOB_NAME, [_ATTEMPTS + symbol])
