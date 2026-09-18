"""`GET /api/v1/companies/{cik}` queries (system design §5).

**52-week range.** Counted in Trading Days, not calendar days (a "52-week"
range is conventionally 252 Trading Days, the number of sessions in a
trading year) -- the last 252 `daily_bars` rows for the company's *price*
Listing, from `public.price_symbol(cik)` (migration 0001): the seeded
`share_class_rules.price_symbol` if that Listing is still active, else the
active primary Listing, else null. DRY pass on #6's review gate: this used
to be a second, disagreeing copy of that rule in Python here (no fallback
to an inactive primary or "the first Listing alphabetically", either of
which could silently use stale prices off a retired ticker) -- now it's the
one function both this query and the market-cap-rebuild job call. The range
itself is the *adjusted* intraday high/low: `high * adj_close / close` and
`low * adj_close / close`, scaling each day's as-traded intraday extreme by
that day's own split/dividend adjustment factor (`adj_close / close`)
rather than reading the stored `adj_close` (a close-only figure) as if it
were the day's range.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

WEEK_52_TRADING_DAYS = 252

_COMPANY_QUERY = text(
    "SELECT cik, name, sector, sub_industry, headquarters, date_added, is_active "
    "FROM companies WHERE cik = :cik"
)

_LISTINGS_QUERY = text(
    "SELECT symbol, is_primary, is_active, first_bar_date, backfill_completed_at FROM listings "
    "WHERE cik = :cik ORDER BY is_primary DESC, symbol"
)

_MARKET_CAP_QUERY = text(
    "SELECT market_cap, shares_as_of, is_multi_class FROM market_caps "
    "WHERE cik = :cik AND trade_date <= :today ORDER BY trade_date DESC LIMIT 1"
)

_FIRST_BAR_DATE_QUERY = text("SELECT min(first_bar_date) FROM listings WHERE cik = :cik")

_WEEK_52_RANGE_QUERY = text(
    """
    SELECT
      max(high * adj_close / close)::numeric(18, 6) AS high,
      min(low * adj_close / close)::numeric(18, 6) AS low
    FROM (
      SELECT high, low, close, adj_close FROM daily_bars
      WHERE symbol = public.price_symbol(:cik) AND trade_date <= :today
      ORDER BY trade_date DESC
      LIMIT :trading_days
    ) recent
    """
)


async def fetch_company_row(conn: AsyncConnection, *, cik: str) -> Row[Any] | None:
    return (await conn.execute(_COMPANY_QUERY, {"cik": cik})).first()


async def fetch_listing_rows(conn: AsyncConnection, *, cik: str) -> Sequence[Row[Any]]:
    return (await conn.execute(_LISTINGS_QUERY, {"cik": cik})).all()


async def fetch_market_cap_row(conn: AsyncConnection, *, cik: str, today: date) -> Row[Any] | None:
    return (await conn.execute(_MARKET_CAP_QUERY, {"cik": cik, "today": today})).first()


async def fetch_first_bar_date(conn: AsyncConnection, *, cik: str) -> date | None:
    first_bar_date: date | None = await conn.scalar(_FIRST_BAR_DATE_QUERY, {"cik": cik})
    return first_bar_date


async def fetch_week_52_range(conn: AsyncConnection, *, cik: str, today: date) -> Row[Any] | None:
    return (
        await conn.execute(
            _WEEK_52_RANGE_QUERY,
            {"cik": cik, "today": today, "trading_days": WEEK_52_TRADING_DAYS},
        )
    ).first()
