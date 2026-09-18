"""Provider-agnostic seams for market data (reliability review).

The Alpaca client itself lands in a later issue; this module is the
contract it implements, so `quotes_poll`/`bars_backfill`/`bars_daily` can be
written and tested against a fake before that client exists. A `Protocol`
means the adapter needs no inheritance -- any object with the right async
methods satisfies it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol


@dataclass(slots=True, frozen=True)
class ProviderQuote:
    symbol: str
    price: Decimal
    observed_at: datetime
    feed: str


class QuoteSource(Protocol):
    async def snapshot(self, symbols: Sequence[str]) -> list[ProviderQuote]:
        """Latest trade per symbol. A symbol with no trade is simply absent
        from the result -- the caller (quotes_poll) records that as a
        per-item failure, not an exception."""
        ...


@dataclass(slots=True, frozen=True)
class ProviderBar:
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class BarSource(Protocol):
    async def daily_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        adjustment: Literal["raw", "all"],
    ) -> list[ProviderBar]:
        """One `adjustment` pass at a time (system design §4: bars_backfill
        and bars_daily each fetch `raw` then `all` and join on
        (symbol, trade_date) themselves -- `close` from the `raw` pass,
        `adj_close` from the `all` pass's `close`)."""
        ...
