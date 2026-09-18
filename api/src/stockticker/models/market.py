from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from stockticker.models.status import MarketClock


class MarketRow(BaseModel):
    symbol: str
    cik: str
    name: str
    sector: str
    is_primary: bool
    price: Decimal | None
    observed_at: datetime | None
    prev_close: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    volume: int | None
    market_cap: Decimal | None
    market_cap_is_approx: bool
    first_bar_date: date | None
    backfill_completed_at: datetime | None


class MarketResponse(BaseModel):
    """Reliability review: carries the same market-clock fields as
    `/api/v1/status` so the client never has to combine two cached queries
    to answer "is the market open" next to the listings themselves."""

    server_time: datetime
    market_clock: MarketClock | None
    listings: list[MarketRow]
