"""`GET /api/v1/listings/{symbol}/bars` queries (system design §5).

A single-symbol date-range scan is already covered by the `daily_bars`
primary key `(symbol, trade_date)` -- no extra index needed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

_LISTING_EXISTS_QUERY = text("SELECT 1 FROM listings WHERE symbol = :symbol")

_BARS_QUERY = text(
    "SELECT trade_date, open, high, low, close, volume, adj_close FROM daily_bars "
    "WHERE symbol = :symbol AND trade_date BETWEEN :from_date AND :to_date "
    "ORDER BY trade_date"
)


async def listing_exists(conn: AsyncConnection, *, symbol: str) -> bool:
    return (await conn.scalar(_LISTING_EXISTS_QUERY, {"symbol": symbol})) is not None


async def fetch_bar_rows(
    conn: AsyncConnection, *, symbol: str, from_date: date, to_date: date
) -> Sequence[Row[Any]]:
    result = await conn.execute(_BARS_QUERY, {"symbol": symbol, "from_date": from_date, "to_date": to_date})
    return result.all()
