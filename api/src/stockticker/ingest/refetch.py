"""The `refetch_requests` contract between the jobs that queue re-fetches
(`bars_daily` for `adj_drift`, `gap_check` for `gap`) and the one that
serves them (`bars_backfill`).

`attempts` counts failed re-fetches and lives only in the row. The serving
job calls exactly two functions:

- `mark_refetch_failed` when a re-fetch raises;
- `finish_refetch` when it commits. That deletes the row, except a `gap`
  row whose gap is still open (the provider returned no bar for the missing
  days), which counts as a failed attempt instead. `gap_check` accepts a gap
  after `MAX_GAP_ATTEMPTS`.

None of these commit.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.ingest.watermarks import read_watermarks

RefetchReason = Literal["adj_drift", "gap"]

MAX_GAP_ATTEMPTS = 3
GAP_STILL_OPEN = "gap still open after re-fetch"
MAX_ERROR_LENGTH = 500

GAP_CHECK_JOB = "gap_check"
ACCEPTED_PREFIX = "accepted:"

_GAPS_SQL = text(
    """
    SELECT l.symbol, array_agg(td.trade_date ORDER BY td.trade_date) AS gaps
    FROM listings l
    CROSS JOIN LATERAL (SELECT max(b.trade_date) AS last_bar FROM daily_bars b WHERE b.symbol = l.symbol) lb
    JOIN trading_days td ON td.trade_date >= l.first_bar_date AND td.trade_date <= lb.last_bar
    WHERE l.is_active AND l.backfill_completed_at IS NOT NULL AND l.first_bar_date IS NOT NULL
      AND (CAST(:symbols AS text[]) IS NULL OR l.symbol = ANY(CAST(:symbols AS text[])))
      AND NOT EXISTS (
        SELECT 1 FROM daily_bars b WHERE b.symbol = l.symbol AND b.trade_date = td.trade_date
      )
    GROUP BY l.symbol
    """
)


async def accepted_gap_days(conn: AsyncConnection) -> dict[str, set[date]]:
    """Gap days `gap_check` has given up on, per symbol."""
    return {
        symbol: {date.fromisoformat(day) for day in json.loads(value)}
        for symbol, value in (await read_watermarks(conn, GAP_CHECK_JOB, ACCEPTED_PREFIX)).items()
    }


async def open_gap_days(conn: AsyncConnection, symbols: Sequence[str] | None = None) -> dict[str, list[date]]:
    """Trading Days with no bar between each backfilled Listing's first bar
    and its latest bar, not counting accepted gaps. Only Listings with at
    least one open gap appear."""
    accepted = await accepted_gap_days(conn)
    result = await conn.execute(_GAPS_SQL, {"symbols": list(symbols) if symbols is not None else None})
    gaps: dict[str, list[date]] = {}
    for row in result:
        open_days = [day for day in row.gaps if day not in accepted.get(row.symbol, set())]
        if open_days:
            gaps[row.symbol] = open_days
    return gaps


async def mark_refetch_failed(conn: AsyncConnection, symbol: str, reason: RefetchReason, error: str) -> None:
    await conn.execute(
        text(
            "UPDATE refetch_requests SET attempts = attempts + 1, last_error = :error "
            "WHERE symbol = :symbol AND reason = :reason AND accepted_at IS NULL"
        ),
        {"symbol": symbol, "reason": reason, "error": error[:MAX_ERROR_LENGTH]},
    )


async def finish_refetch(
    conn: AsyncConnection, symbol: str, reason: RefetchReason, requested_before: datetime
) -> None:
    """A re-fetch committed. Deletes the row unless it was re-requested after
    `requested_before` (the time the serving job selected it), or it is a
    `gap` row whose gap is still open."""
    if reason == "gap" and symbol in await open_gap_days(conn, [symbol]):
        await mark_refetch_failed(conn, symbol, reason, GAP_STILL_OPEN)
        return
    await conn.execute(
        text(
            "DELETE FROM refetch_requests "
            "WHERE symbol = :symbol AND reason = :reason AND requested_at <= :requested_before"
        ),
        {"symbol": symbol, "reason": reason, "requested_before": requested_before},
    )
