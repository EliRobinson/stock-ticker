"""`GET /api/v1/market` query (system design §5).

**Performance.** With ~503 active Listings and ~1.1M `daily_bars` rows, a
naive "latest bar per symbol" query (`GROUP BY symbol` or a window function
over the whole table) has to touch every row. Instead, for each active
Listing, one `LATERAL` subquery against `trading_days` (a ~2,300-row table)
finds the previous Trading Day, bounded by `ORDER BY trade_date DESC LIMIT
1`; the exact `daily_bars` row for that date is then a plain equality join
on the table's own primary key `(symbol, trade_date)`. `market_caps` gets
the same `LATERAL` + `LIMIT 1` treatment against its own `(cik, trade_date)`
primary key. See `EXPLAIN.md` in this package for the measured plan.

**"Previous SIP close".** `daily_bars` is fed from Alpaca's SIP feed
(`feed=sip`, system design §4) while `quotes.price` is IEX. "Previous SIP
close" is the *exact* Trading Day immediately before the Quote's own
`observed_at` (converted to a New York date) -- not "today" and not
"whatever the latest stored bar happens to be": if that specific Trading
Day has no bar (a gap), `prev_close`/`volume` come back null rather than
falling back to an earlier one, because a silent fallback would make a
stale/wrong number look current. A Listing with no Quote at all anchors on
`:today` instead, since there's no `observed_at` to convert.
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
      l.first_bar_date,
      q.price,
      q.observed_at,
      pb.close AS prev_close,
      pb.volume AS prev_volume,
      mc.market_cap,
      COALESCE(mc.is_multi_class, false) AS market_cap_is_approx
    FROM listings l
    JOIN companies c ON c.cik = l.cik
    LEFT JOIN quotes q ON q.symbol = l.symbol
    LEFT JOIN LATERAL (
      SELECT td.trade_date
      FROM trading_days td
      WHERE td.trade_date < COALESCE((q.observed_at AT TIME ZONE 'America/New_York')::date, :today)
      ORDER BY td.trade_date DESC
      LIMIT 1
    ) ptd ON true
    LEFT JOIN daily_bars pb ON pb.symbol = l.symbol AND pb.trade_date = ptd.trade_date
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
