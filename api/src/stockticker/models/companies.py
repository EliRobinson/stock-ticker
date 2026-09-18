from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ListingSummary(BaseModel):
    symbol: str
    is_primary: bool
    is_active: bool
    first_bar_date: date | None
    backfill_completed_at: datetime | None


class MarketCapSummary(BaseModel):
    market_cap: Decimal
    shares_as_of: date
    is_approx: bool


class CompanyDetail(BaseModel):
    cik: str
    name: str
    sector: str
    sub_industry: str | None
    headquarters: str | None
    date_added: date | None
    is_active: bool
    listings: list[ListingSummary]
    market_cap: MarketCapSummary | None
    week_52_high: Decimal | None
    week_52_low: Decimal | None
    first_bar_date: date | None
