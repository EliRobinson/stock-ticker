from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Timeframe = Literal["1d"]


class Bar(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal


class BarsResponse(BaseModel):
    """`timeframe` only ever `"1d"` today; echoed back so the client's cache
    key is unambiguous once intraday timeframes exist (system design §5)."""

    timeframe: Timeframe
    bars: list[Bar]
