"""Contract test for `GET /api/v1/market` (system design §5, amended).

`prev_close` is anchored on the *Quote's own* `observed_at` (converted to a
New York date), not on "today" -- these tests cover the cases that
distinction matters: before the open, across a weekend, across a holiday
gap in `trading_days`, and a genuine data gap (a Trading Day with no bar,
which must come back null, never a silent fallback to an earlier bar).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest_asyncio
import seed
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.timeutil import NY_TZ, today_ny

CIK_QUOTED = "9000000001"
CIK_NO_QUOTE = "9000000002"
CIK_MULTI_CLASS = "9000000003"
CIK_GAP = "9000000004"
CIK_HOLIDAY = "9000000005"
CIK_INACTIVE = "9000000006"
CIK_WEEKEND = "9000000007"
SYMBOL_QUOTED = "ZTQ"
SYMBOL_NO_QUOTE = "ZTN"
SYMBOL_MULTI_CLASS = "ZTM"
SYMBOL_GAP = "ZTG"
SYMBOL_HOLIDAY = "ZTH"
SYMBOL_INACTIVE = "ZTI"
SYMBOL_WEEKEND = "ZTW"

MON = date(2024, 1, 8)
TUE = date(2024, 1, 9)
WED = date(2024, 1, 10)
FRI = date(2024, 1, 5)

# A separate week for the holiday scenario: TUE_H is deliberately never
# inserted into trading_days at all (unlike TUE, which the gap scenario
# needs present with no bar) -- the two can't share a date.
MON_H = date(2024, 1, 15)
WED_H = date(2024, 1, 17)


def _ny_noon(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=NY_TZ).astimezone(UTC)


def _ny_early(d: date) -> datetime:
    """09:00 ET -- before the 09:30 open."""
    return datetime(d.year, d.month, d.day, 9, 0, tzinfo=NY_TZ).astimezone(UTC)


@pytest_asyncio.fixture
async def market_fixture(app_writer_engine: AsyncEngine) -> AsyncIterator[None]:
    today = today_ny()
    prev_day = today - timedelta(days=1)

    async with app_writer_engine.connect() as conn:
        await seed.ensure_trading_days(conn, [prev_day, today, MON, TUE, WED, FRI, MON_H, WED_H])

        await seed.insert_company(conn, cik=CIK_QUOTED, name="Zenith Test Quoted Co")
        await seed.insert_listing(conn, symbol=SYMBOL_QUOTED, cik=CIK_QUOTED, first_bar_date=prev_day)
        await seed.insert_bar(
            conn,
            symbol=SYMBOL_QUOTED,
            trade_date=prev_day,
            open_=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=123_456,
            adj_close=Decimal("100"),
        )
        await seed.insert_quote(conn, symbol=SYMBOL_QUOTED, price=Decimal("105"), observed_at=_ny_noon(today))
        await seed.insert_market_cap(
            conn,
            cik=CIK_QUOTED,
            trade_date=prev_day,
            market_cap=Decimal("500000000000.00"),
            shares_used=5_000_000_000,
            shares_as_of=prev_day,
            is_multi_class=False,
        )

        await seed.insert_company(conn, cik=CIK_NO_QUOTE, name="Zenith Test No Quote Co")
        await seed.insert_listing(conn, symbol=SYMBOL_NO_QUOTE, cik=CIK_NO_QUOTE, first_bar_date=prev_day)
        await seed.insert_bar(
            conn,
            symbol=SYMBOL_NO_QUOTE,
            trade_date=prev_day,
            open_=Decimal("50"),
            high=Decimal("51"),
            low=Decimal("49"),
            close=Decimal("50"),
            volume=1_000,
            adj_close=Decimal("50"),
        )

        await seed.insert_company(conn, cik=CIK_MULTI_CLASS, name="Zenith Test Multi Class Co")
        await seed.insert_listing(
            conn, symbol=SYMBOL_MULTI_CLASS, cik=CIK_MULTI_CLASS, first_bar_date=prev_day
        )
        await seed.insert_market_cap(
            conn,
            cik=CIK_MULTI_CLASS,
            trade_date=prev_day,
            market_cap=Decimal("1000.00"),
            shares_used=100,
            shares_as_of=prev_day,
            is_multi_class=True,
        )

        # Gap: bars on MON and WED, none on TUE. Quote anchored on WED, so
        # the previous Trading Day is TUE -- which has no bar.
        await seed.insert_company(conn, cik=CIK_GAP, name="Zenith Test Gap Co")
        await seed.insert_listing(conn, symbol=SYMBOL_GAP, cik=CIK_GAP, first_bar_date=MON)
        for d, close in [(MON, Decimal("10")), (WED, Decimal("12"))]:
            await seed.insert_bar(
                conn,
                symbol=SYMBOL_GAP,
                trade_date=d,
                open_=close,
                high=close,
                low=close,
                close=close,
                volume=100,
                adj_close=close,
            )
        await seed.insert_quote(conn, symbol=SYMBOL_GAP, price=Decimal("13"), observed_at=_ny_noon(WED))

        # Holiday: the day between MON_H and WED_H is deliberately never a
        # Trading Day at all. A quote anchored on WED_H should skip straight
        # back to MON_H.
        await seed.insert_company(conn, cik=CIK_HOLIDAY, name="Zenith Test Holiday Co")
        await seed.insert_listing(conn, symbol=SYMBOL_HOLIDAY, cik=CIK_HOLIDAY, first_bar_date=MON_H)
        await seed.insert_bar(
            conn,
            symbol=SYMBOL_HOLIDAY,
            trade_date=MON_H,
            open_=Decimal("20"),
            high=Decimal("21"),
            low=Decimal("19"),
            close=Decimal("20"),
            volume=200,
            adj_close=Decimal("20"),
        )
        # Before-open: observed at 09:00 ET on WED_H, still anchors on
        # WED_H's date (not "yesterday relative to now") and finds MON_H.
        await seed.insert_quote(
            conn, symbol=SYMBOL_HOLIDAY, price=Decimal("22"), observed_at=_ny_early(WED_H)
        )

        # Weekend: quote observed on Saturday. Sat/Sun are never in
        # trading_days, so the previous session is FRI, not "yesterday".
        await seed.insert_company(conn, cik=CIK_WEEKEND, name="Zenith Test Weekend Co")
        await seed.insert_listing(conn, symbol=SYMBOL_WEEKEND, cik=CIK_WEEKEND, first_bar_date=FRI)
        await seed.insert_bar(
            conn,
            symbol=SYMBOL_WEEKEND,
            trade_date=FRI,
            open_=Decimal("30"),
            high=Decimal("31"),
            low=Decimal("29"),
            close=Decimal("30"),
            volume=300,
            adj_close=Decimal("30"),
        )
        saturday = date(2024, 1, 6)
        await seed.insert_quote(
            conn, symbol=SYMBOL_WEEKEND, price=Decimal("31"), observed_at=_ny_noon(saturday)
        )

        await seed.insert_company(conn, cik=CIK_INACTIVE, name="Zenith Test Inactive Co")
        await seed.insert_listing(
            conn, symbol=SYMBOL_INACTIVE, cik=CIK_INACTIVE, is_active=False, first_bar_date=prev_day
        )

    yield

    async with app_writer_engine.connect() as conn:
        for cik in (
            CIK_QUOTED,
            CIK_NO_QUOTE,
            CIK_MULTI_CLASS,
            CIK_GAP,
            CIK_HOLIDAY,
            CIK_INACTIVE,
            CIK_WEEKEND,
        ):
            await seed.cleanup_cik(conn, cik=cik)


def _row(body: dict[str, Any], symbol: str) -> dict[str, Any]:
    matches = [row for row in body["listings"] if row["symbol"] == symbol]
    assert len(matches) == 1, f"expected exactly one row for {symbol}, found {len(matches)}"
    return matches[0]  # type: ignore[no-any-return]


def test_market_returns_computed_fields_gzipped(market_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/market", headers={"accept-encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"

    body = response.json()
    assert "server_time" in body
    assert "market_clock" in body
    assert isinstance(body["listings"], list)

    quoted = _row(body, SYMBOL_QUOTED)
    assert quoted["price"] == "105.000000"
    assert quoted["prev_close"] == "100.000000"
    assert quoted["change"] == "5.000000"
    assert quoted["change_pct"] == "0.05"
    assert quoted["volume"] == 123_456
    assert quoted["market_cap"] == "500000000000.00"
    assert quoted["market_cap_is_approx"] is False

    no_quote = _row(body, SYMBOL_NO_QUOTE)
    assert no_quote["price"] is None
    assert no_quote["change"] is None
    assert no_quote["change_pct"] is None
    assert no_quote["prev_close"] == "50.000000"

    multi = _row(body, SYMBOL_MULTI_CLASS)
    assert multi["market_cap_is_approx"] is True

    assert not any(row["symbol"] == SYMBOL_INACTIVE for row in body["listings"])


def test_market_omits_gzip_without_accept_encoding(market_fixture: None, api_client: TestClient) -> None:
    response = api_client.get("/api/v1/market", headers={"accept-encoding": "identity"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_market_prev_close_gap_returns_null_not_a_fallback(
    market_fixture: None, api_client: TestClient
) -> None:
    body = api_client.get("/api/v1/market").json()
    gap = _row(body, SYMBOL_GAP)
    # TUE (the Trading Day immediately before the quote's WED anchor) has
    # no bar -- must be null, never MON's bar.
    assert gap["prev_close"] is None
    assert gap["volume"] is None


def test_market_prev_close_skips_weekend(market_fixture: None, api_client: TestClient) -> None:
    body = api_client.get("/api/v1/market").json()
    weekend = _row(body, SYMBOL_WEEKEND)
    assert weekend["prev_close"] == "30.000000"


def test_market_prev_close_skips_holiday_gap_in_trading_days(
    market_fixture: None, api_client: TestClient
) -> None:
    body = api_client.get("/api/v1/market").json()
    holiday = _row(body, SYMBOL_HOLIDAY)
    # TUE was never a Trading Day at all; the previous session is MON.
    assert holiday["prev_close"] == "20.000000"


def test_market_prev_close_before_open_uses_quote_date_not_time(
    market_fixture: None, api_client: TestClient
) -> None:
    body = api_client.get("/api/v1/market").json()
    holiday = _row(body, SYMBOL_HOLIDAY)
    # Same fixture's quote is at 09:00 ET (pre-open) on WED; only the date
    # component of observed_at should matter.
    assert holiday["observed_at"].startswith("2024-01-17")
    assert holiday["prev_close"] == "20.000000"
