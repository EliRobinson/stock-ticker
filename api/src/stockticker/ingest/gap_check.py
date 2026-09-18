"""`gap_check` (system design §4): find Trading Days with no Daily Bar and
queue them for `bars_backfill` through `refetch_requests` (reason `gap`).
This job never fetches bars itself.

Scope: active Listings with `backfill_completed_at` set. A gap is a Trading
Day between the Listing's `first_bar_date` and its latest bar with no bar
(`refetch.open_gap_days`).

One `refetch_requests` row per Listing covers all its gaps (`from_date` is
the earliest). Its `attempts` column is the only attempt count:
`bars_backfill` raises it through `refetch.mark_refetch_failed` or
`refetch.finish_refetch` each time a re-fetch fails or leaves the gap open,
and deletes the row once a re-fetch closes it.

Each night, for a Listing with open gaps:

- no row, or an accepted row (older gaps were accepted; these are new):
  queue a fresh row;
- a row still being retried: widen its `from_date` if an earlier gap
  appeared;
- a row with `MAX_GAP_ATTEMPTS` failed attempts: accept the gaps. The row
  stays with `accepted_at` set, so `/api/v1/status` can count accepted gaps
  and `bars_backfill` leaves it alone, and the accepted days are remembered
  (`accepted:{symbol}` watermark) so they are not queued again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.job import JobContext, JobResult, JobSkipped
from stockticker.ingest.refetch import (
    ACCEPTED_PREFIX,
    GAP_CHECK_JOB,
    MAX_GAP_ATTEMPTS,
    RefetchReason,
    accepted_gap_days,
    open_gap_days,
)
from stockticker.ingest.watermarks import write_watermark
from stockticker.logging import get_logger

logger = get_logger(__name__)

REASON: RefetchReason = "gap"

_ANY_LISTING_IN_SCOPE_SQL = text(
    "SELECT symbol FROM listings "
    "WHERE is_active AND backfill_completed_at IS NOT NULL AND first_bar_date IS NOT NULL "
    "LIMIT 1"
)


@dataclass(slots=True)
class GapCheckSummary:
    queued: int = 0
    waiting: int = 0
    accepted: int = 0


@dataclass(frozen=True, slots=True)
class _Request:
    attempts: int
    accepted: bool


async def gap_check(ctx: JobContext) -> JobResult:
    return await run_gap_check(ctx.engine)


async def run_gap_check(engine: AsyncEngine) -> JobResult:
    async with engine.connect() as conn:
        summary = await check_gaps(conn)
        await conn.commit()
    logger.info("gap_check.done", queued=summary.queued, waiting=summary.waiting, accepted=summary.accepted)
    return JobResult(rows_written=summary.queued + summary.accepted)


async def check_gaps(conn: AsyncConnection) -> GapCheckSummary:
    """Queue, keep waiting on, or accept every open gap. Does not commit."""
    if not (await conn.execute(_ANY_LISTING_IN_SCOPE_SQL)).first():
        raise JobSkipped("no active Listings with a completed backfill")
    gaps = await open_gap_days(conn)
    requests = await _gap_requests(conn)
    accepted_days = await accepted_gap_days(conn)

    summary = GapCheckSummary()
    for symbol, days in gaps.items():
        request = requests.get(symbol)
        if request is None or request.accepted:
            await _queue(conn, symbol, days[0])
            summary.queued += 1
        elif request.attempts >= MAX_GAP_ATTEMPTS:
            await _accept(conn, symbol, days, accepted_days.get(symbol, set()))
            summary.accepted += 1
            logger.info("gap_check.accepted", symbol=symbol, gaps=[day.isoformat() for day in days])
        else:
            await _widen(conn, symbol, days[0])
            summary.waiting += 1
    return summary


async def _gap_requests(conn: AsyncConnection) -> dict[str, _Request]:
    result = await conn.execute(
        text(
            "SELECT symbol, attempts, accepted_at IS NOT NULL AS accepted "
            "FROM refetch_requests WHERE reason = :r"
        ),
        {"r": REASON},
    )
    return {row.symbol: _Request(attempts=row.attempts, accepted=row.accepted) for row in result}


async def _queue(conn: AsyncConnection, symbol: str, from_date: date) -> None:
    await conn.execute(
        text(
            "INSERT INTO refetch_requests (symbol, reason, from_date, requested_at) "
            "VALUES (:symbol, :reason, :from_date, now()) "
            "ON CONFLICT (symbol, reason) DO UPDATE SET from_date = excluded.from_date, "
            "attempts = 0, last_error = NULL, accepted_at = NULL, requested_at = now()"
        ),
        {"symbol": symbol, "reason": REASON, "from_date": from_date},
    )


async def _widen(conn: AsyncConnection, symbol: str, from_date: date) -> None:
    await conn.execute(
        text(
            "UPDATE refetch_requests SET from_date = LEAST(from_date, :from_date) "
            "WHERE symbol = :symbol AND reason = :reason AND accepted_at IS NULL"
        ),
        {"symbol": symbol, "reason": REASON, "from_date": from_date},
    )


async def _accept(conn: AsyncConnection, symbol: str, days: list[date], already_accepted: set[date]) -> None:
    await conn.execute(
        text(
            "UPDATE refetch_requests SET accepted_at = now(), from_date = :from_date "
            "WHERE symbol = :symbol AND reason = :reason"
        ),
        {"symbol": symbol, "reason": REASON, "from_date": days[0]},
    )
    await write_watermark(
        conn,
        GAP_CHECK_JOB,
        ACCEPTED_PREFIX + symbol,
        json.dumps(sorted(day.isoformat() for day in already_accepted | set(days))),
    )
