"""Shared `ProviderBar` factory for unit and integration sink tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stockticker.ingest.providers import ProviderBar


def provider_bar(**overrides: object) -> ProviderBar:
    defaults: dict[str, object] = {
        "symbol": "TST",
        "trade_date": date(2024, 1, 2),
        "open": Decimal("10.00"),
        "high": Decimal("11.00"),
        "low": Decimal("9.50"),
        "close": Decimal("10.50"),
        "volume": 1_000,
        "adj_close": Decimal("10.40"),
        "source": "alpaca",
    }
    defaults.update(overrides)
    return ProviderBar(**defaults)  # type: ignore[arg-type]
