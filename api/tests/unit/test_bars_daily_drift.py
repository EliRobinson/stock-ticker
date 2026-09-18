"""`detect_drift` (system design §4, `bars_daily`) against fakes only, no
HTTP or database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stockticker.ingest.jobs.bars_daily import DRIFT_RELATIVE_TOLERANCE, detect_drift
from stockticker.ingest.providers import ProviderBar


def _bar(symbol: str, d: date, adj_close: str) -> ProviderBar:
    return ProviderBar(
        symbol=symbol,
        trade_date=d,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=1,
        adj_close=Decimal(adj_close),
        source="alpaca",
    )


def test_no_drift_when_adj_close_is_unchanged() -> None:
    rows = [_bar("AAPL", date(2026, 1, 2), "100.000000")]
    assert detect_drift(rows, {date(2026, 1, 2): Decimal("100.000000")}) is False


def test_no_drift_for_a_date_with_nothing_stored_yet() -> None:
    rows = [_bar("AAPL", date(2026, 1, 2), "100")]
    assert detect_drift(rows, {}) is False


def test_drift_when_relative_difference_exceeds_tolerance() -> None:
    stored = Decimal("100.00")
    new = stored * (Decimal(1) + DRIFT_RELATIVE_TOLERANCE * 10)
    rows = [_bar("AAPL", date(2026, 1, 2), str(new))]
    assert detect_drift(rows, {date(2026, 1, 2): stored}) is True


def test_no_drift_just_under_the_tolerance() -> None:
    stored = Decimal("100.00")
    new = stored * (Decimal(1) + DRIFT_RELATIVE_TOLERANCE / 10)
    rows = [_bar("AAPL", date(2026, 1, 2), str(new))]
    assert detect_drift(rows, {date(2026, 1, 2): stored}) is False
