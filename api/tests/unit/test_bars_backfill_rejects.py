"""`daily_bars_isolating_rejects` -- provider 400 / invalid-symbol handling
without HTTP or a database (issue #38)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import httpx
import pytest

from stockticker.ingest.jobs.bars_backfill import (
    daily_bars_isolating_rejects,
    is_provider_symbol_rejection,
)
from stockticker.ingest.providers import ProviderBar


def _bar(symbol: str) -> ProviderBar:
    return ProviderBar(
        symbol=symbol,
        trade_date=date(2020, 1, 2),
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=1,
        adj_close=Decimal("1"),
        source="alpaca",
    )


class _RejectingSource:
    def __init__(self, bad: set[str]) -> None:
        self.bad = bad
        self.calls: list[tuple[str, ...]] = []

    async def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> list[ProviderBar]:
        self.calls.append(tuple(symbols))
        rejected = [symbol for symbol in symbols if symbol in self.bad]
        if rejected:
            request = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars")
            response = httpx.Response(400, request=request, text=f"invalid symbol: {rejected[0]}")
            raise httpx.HTTPStatusError("bad request", request=request, response=response)
        return [_bar(symbol) for symbol in symbols]


class _NetworkErrorSource:
    async def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> list[ProviderBar]:
        raise httpx.ConnectError("connection refused")


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(400, request=httpx.Request("GET", "https://example.com")),
            ),
            True,
        ),
        (
            httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(500, request=httpx.Request("GET", "https://example.com")),
            ),
            False,
        ),
        (RuntimeError("invalid symbol: T131793"), True),
        (RuntimeError("connection reset"), False),
    ],
)
def test_is_provider_symbol_rejection(exc: BaseException, expected: bool) -> None:
    assert is_provider_symbol_rejection(exc) is expected


async def test_isolating_rejects_skips_bad_symbols_and_keeps_good_ones() -> None:
    source = _RejectingSource({"T131793", "T137FB9"})

    bars, failed = await daily_bars_isolating_rejects(
        source, ["AAPL", "T131793", "MSFT", "T137FB9"], date(2018, 1, 1), date(2020, 1, 1)
    )

    assert {bar.symbol for bar in bars} == {"AAPL", "MSFT"}
    assert {item.key for item in failed} == {"T131793", "T137FB9"}
    assert len(source.calls) >= 2


async def test_a_network_error_is_not_treated_as_a_symbol_rejection() -> None:
    with pytest.raises(httpx.ConnectError):
        await daily_bars_isolating_rejects(
            _NetworkErrorSource(), ["AAPL", "MSFT"], date(2018, 1, 1), date(2020, 1, 1)
        )
