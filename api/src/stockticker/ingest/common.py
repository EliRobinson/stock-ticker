"""Shared helpers for the Alpaca ingest jobs -- code every job in
`ingest/jobs/` needed a copy of before this module existed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.ingest.job import FailedItem
from stockticker.ingest.providers import ProviderBar
from stockticker.timeutil import NY_TZ

HISTORY_START = date(2018, 1, 1)

ALPACA_SOURCE = "alpaca"
FEED_SIP = "sip"
FEED_IEX = "iex"

# A bar this far outside its own open/close is a bad print, not a real move
# -- clamped rather than dropped, so the row still exists for the date
# (system design: every active Trading Day has a row).
BAR_SANITY_HIGH_RATIO = Decimal("1.5")
BAR_SANITY_LOW_RATIO = Decimal("0.5")


def ny_date(dt: datetime) -> date:
    """A UTC-ish timestamp's calendar date in New York time (system
    design: "converted to a New York date explicitly, never truncated from
    UTC"). Proposed to the foundation as `timeutil.ny_date` (asked
    a09e0b3ae33bc8d7e directly); kept as a single local copy here until
    that lands, per the DRY-pass note."""
    return dt.astimezone(NY_TZ).date()


def chunked(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


async def active_symbols(conn: AsyncConnection, *, include_inactive: bool = False) -> list[str]:
    """Listings to work a batch over. `include_inactive=True` is for a job
    that still needs to resolve a now-inactive symbol -- e.g.
    `corporate_actions_sync` linking a name change through the *old*
    Listing, which is inactive by the time the rename lands."""
    where = "" if include_inactive else "WHERE is_active"
    rows = (await conn.execute(text(f"SELECT symbol FROM listings {where} ORDER BY symbol"))).all()
    await conn.commit()
    return [row.symbol for row in rows]


def group_by_symbol(bars: list[ProviderBar]) -> dict[str, list[ProviderBar]]:
    grouped: dict[str, list[ProviderBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    return grouped


def to_jsonb(value: dict[str, Any]) -> str:
    return json.dumps(value)


def sanitize_bars(bars: list[ProviderBar]) -> tuple[list[ProviderBar], list[FailedItem]]:
    """A SIP bad print (a `high`/`low` far outside the bar's own open/close)
    would otherwise draw a false spike on the chart. A bar this far off is
    clamped to its own open/close range rather than dropped -- every
    active Trading Day still gets a row -- and recorded as a failed item
    naming the symbol, date, and original value."""
    clean: list[ProviderBar] = []
    failed: list[FailedItem] = []
    for bar in bars:
        body_high = max(bar.open, bar.close)
        body_low = min(bar.open, bar.close)
        bad_high = bar.high > body_high * BAR_SANITY_HIGH_RATIO
        bad_low = bar.low < body_low * BAR_SANITY_LOW_RATIO
        if not bad_high and not bad_low:
            clean.append(bar)
            continue
        original = bar.high if bad_high else bar.low
        clean.append(
            _replace_bar(bar, high=body_high if bad_high else bar.high, low=body_low if bad_low else bar.low)
        )
        failed.append(
            FailedItem(
                key=f"{bar.symbol}:{bar.trade_date}",
                error=f"bad print, clamped: {'high' if bad_high else 'low'} was {original}",
            )
        )
    return clean, failed


def _replace_bar(bar: ProviderBar, *, high: Decimal, low: Decimal) -> ProviderBar:
    return ProviderBar(
        symbol=bar.symbol,
        trade_date=bar.trade_date,
        open=bar.open,
        high=high,
        low=low,
        close=bar.close,
        volume=bar.volume,
        adj_close=bar.adj_close,
        source=bar.source,
    )


__all__ = [
    "ALPACA_SOURCE",
    "BAR_SANITY_HIGH_RATIO",
    "BAR_SANITY_LOW_RATIO",
    "FEED_IEX",
    "FEED_SIP",
    "HISTORY_START",
    "active_symbols",
    "chunked",
    "group_by_symbol",
    "ny_date",
    "sanitize_bars",
    "to_jsonb",
]
