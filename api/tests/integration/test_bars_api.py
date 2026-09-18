"""Contract test for `GET /api/v1/listings/{symbol}/bars` (system design
§5, amended: `timeframe`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest_asyncio
import seed
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

CIK = "9000000201"
SYMBOL = "BRK.B"
DAY_1 = date(2024, 1, 2)
DAY_2 = date(2024, 1, 3)


@pytest_asyncio.fixture
async def bars_fixture(app_writer_engine: AsyncEngine) -> AsyncIterator[None]:
    async with app_writer_engine.connect() as conn:
        await seed.ensure_trading_days(conn, [DAY_1, DAY_2])
        await seed.insert_company(conn, cik=CIK, name="Zenith Test Bars Co")
        await seed.insert_listing(conn, symbol=SYMBOL, cik=CIK, first_bar_date=DAY_1)
        await seed.insert_bar(
            conn,
            symbol=SYMBOL,
            trade_date=DAY_1,
            open_=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10.5"),
            volume=100,
            adj_close=Decimal("10.5"),
        )
        await seed.insert_bar(
            conn,
            symbol=SYMBOL,
            trade_date=DAY_2,
            open_=Decimal("10.5"),
            high=Decimal("12"),
            low=Decimal("10"),
            close=Decimal("11.5"),
            volume=200,
            adj_close=Decimal("11.5"),
        )

    yield

    async with app_writer_engine.connect() as conn:
        await seed.cleanup_cik(conn, cik=CIK)


def test_bars_default_timeframe_returns_ohlcv_and_adj_close(
    bars_fixture: None, api_client: TestClient
) -> None:
    response = api_client.get(
        f"/api/v1/listings/{SYMBOL}/bars",
        params={"from": DAY_1.isoformat(), "to": DAY_2.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timeframe"] == "1d"
    assert "symbol" not in body
    assert [bar["trade_date"] for bar in body["bars"]] == [DAY_1.isoformat(), DAY_2.isoformat()]
    # numeric(18,6) echoes the DB's own scale rather than trimming zeros.
    assert body["bars"][0]["adj_close"] == "10.500000"
    assert body["bars"][1]["close"] == "11.500000"


def test_bars_normalizes_symbol_dash_and_case(bars_fixture: None, api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/listings/brk-b/bars", params={"from": DAY_1.isoformat(), "to": DAY_2.isoformat()}
    )
    assert response.status_code == 200
    assert len(response.json()["bars"]) == 2


def test_bars_invalid_timeframe_is_422(bars_fixture: None, api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/listings/{SYMBOL}/bars", params={"timeframe": "5m"})
    assert response.status_code == 422


def test_bars_from_after_to_is_422(bars_fixture: None, api_client: TestClient) -> None:
    response = api_client.get(
        f"/api/v1/listings/{SYMBOL}/bars", params={"from": DAY_2.isoformat(), "to": DAY_1.isoformat()}
    )
    assert response.status_code == 422
    assert response.json()["type"] == "https://stockticker.local/problems/invalid-range"


def test_bars_unknown_symbol_is_404(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/listings/NOPE999/bars")
    assert response.status_code == 404
    body = response.json()
    assert body["type"] == "https://stockticker.local/problems/unknown-symbol"
