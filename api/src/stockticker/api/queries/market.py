"""`GET /api/v1/market` query (system design §5).

**Performance.** With ~503 active Listings and ~1.1M `daily_bars` rows, a
naive "latest bar per symbol" query (`GROUP BY symbol` or a window function
over the whole table) has to touch every row. Instead, for each active
Listing this calls `public.prev_trading_day` (migration 0001, a ~2,300-row
`trading_days` lookup) to get the exact previous Trading Day, then joins
`daily_bars` for that date -- a plain equality lookup on the table's own
primary key `(symbol, trade_date)`. `market_caps` gets the same `LATERAL` +
`LIMIT 1` treatment against its own `(cik, trade_date)` primary key (no
shared function for that one). See `EXPLAIN.md` in this package for the
measured plan.

**"Previous SIP close".** `daily_bars` is fed from Alpaca's SIP feed
(`feed=sip`, system design §4) while `quotes.price` is IEX. "Previous SIP
close" is the *exact* Trading Day immediately before the Quote's own
`observed_at` (converted to a New York date) -- not "today" and not
"whatever the latest stored bar happens to be": if that specific Trading
Day has no bar (a gap), `prev_close`/`volume` come back null rather than
falling back to an earlier one, because a silent fallback would make a
stale/wrong number look current. A Listing with no Quote at all anchors on
`:today` instead, since there's no `observed_at` to convert.

DRY pass on #6's review gate: this used to compute "the previous Trading
Day" with its own `LATERAL` subquery, a second copy of the same rule the
foundation's `ai.quotes` view also had (and the two disagreed on edge
cases). `public.prev_trading_day(anchor date)` is now the one place that
rule is written.

**`change`/`change_pct`.** Computed here, in SQL, rather than in Python
after the query runs (issue #24). Null `price`/`prev_close` (unmatched
`LEFT JOIN`) propagate through subtraction and division; `NULLIF(prev_close,
0)` makes `change_pct` null on a zero close (defensive -- both columns
carry a `> 0` CHECK). `trim_scale` strips the padded trailing zeros a
`numeric` division produces, matching the precision `Decimal` division gave
when this ran in Python (`5/100` -> `0.05`, not `0.050000...`); `change` is
a same-scale subtraction and needs no trimming. Every column here is named
to match `MarketRow` directly, so `routers/market.py::_market_row` is a
plain `model_validate` with no Python-side dict merging.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

MARKET_QUERY = text(
    """
    SELECT
      l.symbol,
      l.cik,
      c.name,
      c.sector,
      l.is_primary,
      l.first_bar_date,
      l.backfill_completed_at,
      q.price,
      q.observed_at,
      pb.close AS prev_close,
      pb.volume AS volume,
      q.price - pb.close AS change,
      trim_scale((q.price - pb.close) / NULLIF(pb.close, 0)) AS change_pct,
      mc.market_cap,
      COALESCE(mc.is_multi_class, false) AS market_cap_is_approx
    FROM listings l
    JOIN companies c ON c.cik = l.cik
    LEFT JOIN quotes q ON q.symbol = l.symbol
    LEFT JOIN daily_bars pb
      ON pb.symbol = l.symbol
      AND pb.trade_date = public.prev_trading_day(
        COALESCE((q.observed_at AT TIME ZONE 'America/New_York')::date, :today)
      )
    LEFT JOIN LATERAL (
      SELECT m.market_cap, m.is_multi_class
      FROM market_caps m
      WHERE m.cik = l.cik AND m.trade_date <= :today
      ORDER BY m.trade_date DESC
      LIMIT 1
    ) mc ON true
    WHERE l.is_active
    ORDER BY l.symbol;
    """
)


async def fetch_market_rows(conn: AsyncConnection, *, today: date) -> Sequence[Row[Any]]:
    result = await conn.execute(MARKET_QUERY, {"today": today})
    return result.all()
