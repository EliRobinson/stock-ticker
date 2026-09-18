"""Provider-agnostic seams for market data (system design §4).

The Alpaca client itself lands in a later issue; this module is the
contract it implements, so `quotes_poll`/`bars_backfill`/`bars_daily` can
be written and tested against a fake before that client exists. A
`Protocol` means the adapter needs no inheritance -- any object with the
right async methods satisfies it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


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

    def stream(self, symbols: Sequence[str]) -> AsyncIterator[ProviderQuote]:
        """A push feed of quotes as they trade, for the paid-SIP-websocket
        upgrade path (§9/§10) -- `snapshot` stays the poll-based default."""
        ...


@dataclass(slots=True, frozen=True)
class ProviderBar:
    """Fully joined: as-traded OHLCV, `adj_close` from the adjusted pass,
    and the adapter's own source tag -- ready for `upsert_bars`. The
    adapter does the raw/all join itself (system design §4)."""

    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal
    source: str


class BarSource(Protocol):
    async def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> list[ProviderBar]:
        """Daily Bars for `symbols` over `[start, end]`, joined and ready to
        upsert."""
        ...
