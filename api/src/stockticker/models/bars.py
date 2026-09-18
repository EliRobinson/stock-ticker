from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Bar(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal
