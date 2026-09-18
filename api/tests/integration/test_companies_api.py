"""Contract test for `GET /api/v1/companies/{cik}` (system design §5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal

import pytest_asyncio
import seed
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.timeutil import today_ny

CIK = "9000000101"
SYMBOL = "ZTC"
CIK_NO_MARKET_CAP = "9000000102"
SYMBOL_NO_MARKET_CAP = "ZTNM"
CIK_INACTIVE = "9000000103"
SYMBOL_INACTIVE = "ZTIC"
CIK_WINDOW = "9000000104"
SYMBOL_WINDOW = "ZTW2"


@pytest_asyncio.fixture
async def company_fixture(app_writer_engine: AsyncEngine) -> AsyncIterator[None]:
    today = today_ny()
    old_day = today - timedelta(days=300)
    recent_day = today - timedelta(days=1)

    async with app_writer_engine.connect() as conn:
        await seed.ensure_trading_days(conn, [old_day, recent_day])
        await seed.insert_company(
            conn, cik=CIK, name="Zenith Test Company", date_added=today - timedelta(days=1000)
        )
        await seed.insert_listing(conn, symbol=SYMBOL, cik=CIK, first_bar_date=old_day)
        # Adjusted intraday high/low = high*adj_close/close, low*adj_close/close.
        # old_day: ratio 0.5 (a later split halves it in adjusted terms).
        await seed.insert_bar(
            conn,
            symbol=SYMBOL,
            trade_date=old_day,
            open_=Decimal("190"),
            high=Decimal("200"),
            low=Decimal("180"),
            close=Decimal("190"),
            volume=1000,
            adj_close=Decimal("95"),
        )
        # recent_day: ratio 1 (no further adjustment).
        await seed.insert_bar(
            conn,
            symbol=SYMBOL,
            trade_date=recent_day,
            open_=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=2000,
            adj_close=Decimal("100"),
        )
        await seed.insert_market_cap(
            conn,
            cik=CIK,
            trade_date=recent_day,
            market_cap=Decimal("999.00"),
            shares_used=10,
            shares_as_of=recent_day,
            is_multi_class=False,
        )

        # No market_caps row at all (e.g. Berkshire: "no whole-company share
        # count" -- market cap is unavailable, not zero).
        await seed.insert_company(conn, cik=CIK_NO_MARKET_CAP, name="Zenith Test No Market Cap Co")
        await seed.insert_listing(conn, symbol=SYMBOL_NO_MARKET_CAP, cik=CIK_NO_MARKET_CAP)

        await seed.insert_company(conn, cik=CIK_INACTIVE, name="Zenith Test Inactive Co", is_active=False)
        await seed.insert_listing(conn, symbol=SYMBOL_INACTIVE, cik=CIK_INACTIVE, is_active=False)

    yield

    async with app_writer_engine.connect() as conn:
        await seed.cleanup_cik(conn, cik=CIK)
        await seed.cleanup_cik(conn, cik=CIK_NO_MARKET_CAP)
        await seed.cleanup_cik(conn, cik=CIK_INACTIVE)


@pytest_asyncio.fixture
async def window_fixture(app_writer_engine: AsyncEngine) -> AsyncIterator[date]:
    """253 consecutive Trading Days of bars; the oldest one (254 Trading
    Days back from `end`, i.e. outside the 252-day window) carries an
    extreme high that must NOT show up in the 52-week range."""
    # A date range that doesn't overlap any other test file's dates --
    # `trading_days` rows aren't cleaned up per test (they're a shared,
    # append-only calendar), so a 253-consecutive-day span here would
    # otherwise poison "this date isn't a Trading Day" assumptions
    # elsewhere (e.g. test_market_api.py's holiday-gap fixture).
    end = date(2019, 6, 28)
    days = [end - timedelta(days=i) for i in range(253)]
    days.reverse()

    async with app_writer_engine.connect() as conn:
        await seed.ensure_trading_days(conn, days)
        await seed.insert_company(conn, cik=CIK_WINDOW, name="Zenith Test Window Co")
        await seed.insert_listing(conn, symbol=SYMBOL_WINDOW, cik=CIK_WINDOW, first_bar_date=days[0])
        for i, d in enumerate(days):
            is_outlier = i == 0
            high = Decimal("99999") if is_outlier else Decimal("110")
            low = Decimal("99998") if is_outlier else Decimal("90")
            close = Decimal("99998") if is_outlier else Decimal("100")
            await seed.insert_bar(
                conn,
                symbol=SYMBOL_WINDOW,
                trade_date=d,
                open_=close,
                high=high,
                low=low,
                close=close,
                volume=100,
                adj_close=close,
            )

    yield end

    async with app_writer_engine.connect() as conn:
        await seed.cleanup_cik(conn, cik=CIK_WINDOW)


def test_company_detail_returns_listings_market_cap_and_52w_range(
    company_fixture: None, api_client: TestClient
) -> None:
    response = api_client.get(f"/api/v1/companies/{CIK}")
    assert response.status_code == 200
    body = response.json()

    assert body["cik"] == CIK
    assert body["name"] == "Zenith Test Company"
    assert body["is_active"] is True
    assert [listing["symbol"] for listing in body["listings"]] == [SYMBOL]
    assert body["market_cap"]["market_cap"] == "999.00"
    assert body["market_cap"]["is_approx"] is False
    assert body["week_52_high"] == "110.000000"
    assert body["week_52_low"] == "90.000000"


def test_company_with_no_market_caps_row_returns_null_not_zero(
    company_fixture: None, api_client: TestClient
) -> None:
    response = api_client.get(f"/api/v1/companies/{CIK_NO_MARKET_CAP}")
    assert response.status_code == 200
    assert response.json()["market_cap"] is None


def test_inactive_company_still_returns_200(company_fixture: None, api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/companies/{CIK_INACTIVE}")
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["listings"][0]["is_active"] is False


def test_52w_range_excludes_bars_outside_252_trading_days(
    window_fixture: date, api_client: TestClient
) -> None:
    response = api_client.get(f"/api/v1/companies/{CIK_WINDOW}")
    assert response.status_code == 200
    body = response.json()
    assert body["week_52_high"] == "110.000000"
    assert body["week_52_low"] == "90.000000"


def test_unknown_cik_is_404_problem_json(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/companies/0000000000")
    assert response.status_code == 404
    body = response.json()
    assert body["status"] == 404
    assert body["type"] == "https://stockticker.local/problems/unknown-cik"
