"""`ingest.common` helpers against fakes only, no HTTP or database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stockticker.ingest.common import chunked, group_by_symbol, sanitize_bars
from stockticker.ingest.providers import ProviderBar


def _bar(open_: str, high: str, low: str, close: str) -> ProviderBar:
    return ProviderBar(
        symbol="NVDA",
        trade_date=date(2024, 6, 10),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1,
        adj_close=Decimal(close),
        source="alpaca",
    )


def test_chunked_splits_into_fixed_size_groups() -> None:
    assert list(chunked(["A", "B", "C", "D", "E"], 2)) == [["A", "B"], ["C", "D"], ["E"]]


def test_chunked_of_empty_sequence_yields_nothing() -> None:
    assert list(chunked([], 3)) == []


def test_group_by_symbol_splits_a_flat_list() -> None:
    aapl = _bar("1", "1", "1", "1")
    msft = ProviderBar(
        symbol="MSFT",
        trade_date=date(2024, 6, 10),
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=1,
        adj_close=Decimal("1"),
        source="alpaca",
    )
    grouped = group_by_symbol([aapl, msft])
    assert set(grouped) == {"NVDA", "MSFT"}
    assert grouped["NVDA"] == [aapl]


def test_sanitize_bars_passes_a_normal_bar_through_unchanged() -> None:
    bar = _bar("120.37", "122.10", "119.50", "121.79")
    clean, failed = sanitize_bars([bar])
    assert clean == [bar]
    assert failed == []


def test_sanitize_bars_clamps_a_high_that_is_a_bad_print() -> None:
    """NVDA's 2024-06-10 SIP bar: open 120.37, close 121.79, but high
    195.95 -- a real print would never spike that far above the body in a
    single session; clamped to the body's own high instead of dropped."""
    bar = _bar("120.37", "195.95", "119.50", "121.79")

    clean, failed = sanitize_bars([bar])

    assert len(clean) == 1
    assert clean[0].high == Decimal("121.79")  # max(open, close)
    assert clean[0].low == bar.low  # untouched
    assert len(failed) == 1
    assert failed[0].key == "NVDA:2024-06-10"
    assert "195.95" in failed[0].error


def test_sanitize_bars_clamps_a_low_that_is_a_bad_print() -> None:
    bar = _bar("120.37", "122.10", "10.00", "121.79")

    clean, failed = sanitize_bars([bar])

    assert clean[0].low == Decimal("120.37")  # min(open, close)
    assert len(failed) == 1


def test_sanitize_bars_leaves_a_bar_just_inside_tolerance_alone() -> None:
    # high = 1.5x the body high exactly -- the check is strictly greater than.
    bar = _bar("100", "150", "95", "100")
    clean, failed = sanitize_bars([bar])
    assert clean == [bar]
    assert failed == []
