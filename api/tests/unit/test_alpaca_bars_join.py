"""`AlpacaBarSource`/`join_raw_bars` -- the raw/adjusted join that
`providers.BarSource.daily_bars` now expects pre-done -- against fakes
only, no HTTP."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from stockticker.ingest.alpaca.bars import AlpacaBarSource, join_raw_bars
from stockticker.ingest.alpaca.client import RawBar


def _raw(symbol: str, d: date, close: str) -> RawBar:
    return RawBar(
        symbol=symbol,
        trade_date=d,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=10,
    )


def test_join_raw_bars_keeps_only_dates_present_in_both_passes() -> None:
    raw = {"AAPL": [_raw("AAPL", date(2026, 1, 2), "10"), _raw("AAPL", date(2026, 1, 5), "11")]}
    adjusted = {"AAPL": [_raw("AAPL", date(2026, 1, 2), "9.5")]}  # 1/5 missing from the adjusted pass

    joined = join_raw_bars(raw, adjusted)

    assert [bar.trade_date for bar in joined] == [date(2026, 1, 2)]
    assert joined[0].close == Decimal("10")  # from the raw pass
    assert joined[0].adj_close == Decimal("9.5")  # from the adjusted pass's close
    assert joined[0].source == "alpaca"


def test_join_raw_bars_covers_every_symbol_in_the_raw_pass() -> None:
    raw = {
        "AAPL": [_raw("AAPL", date(2026, 1, 2), "1")],
        "MSFT": [_raw("MSFT", date(2026, 1, 2), "2")],
    }
    adjusted = {
        "AAPL": [_raw("AAPL", date(2026, 1, 2), "1")],
        "MSFT": [_raw("MSFT", date(2026, 1, 2), "2")],
    }

    joined = join_raw_bars(raw, adjusted)

    assert {bar.symbol for bar in joined} == {"AAPL", "MSFT"}


def test_join_raw_bars_drops_a_symbol_missing_from_the_adjusted_pass() -> None:
    raw = {"AAPL": [_raw("AAPL", date(2026, 1, 2), "1")]}
    adjusted: dict[str, list[RawBar]] = {}

    assert join_raw_bars(raw, adjusted) == []


class _FakeRawClient:
    def __init__(self, raw: dict[str, list[RawBar]], adjusted: dict[str, list[RawBar]]) -> None:
        self._raw = raw
        self._adjusted = adjusted
        self.calls: list[str] = []

    async def get_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        adjustment: Literal["raw", "all"],
        timeframe: str = "1Day",
        feed: str = "sip",
    ) -> dict[str, list[RawBar]]:
        self.calls.append(adjustment)
        return self._raw if adjustment == "raw" else self._adjusted


async def test_alpaca_bar_source_makes_one_call_per_adjustment_pass() -> None:
    raw = {"AAPL": [_raw("AAPL", date(2026, 1, 2), "1")]}
    adjusted = {"AAPL": [_raw("AAPL", date(2026, 1, 2), "1.1")]}
    client = _FakeRawClient(raw, adjusted)

    bars = await AlpacaBarSource(client).daily_bars(["AAPL"], date(2026, 1, 1), date(2026, 1, 5))

    assert client.calls == ["raw", "all"]
    assert len(bars) == 1
    assert bars[0].adj_close == Decimal("1.1")
