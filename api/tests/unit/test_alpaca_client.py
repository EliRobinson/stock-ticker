"""`AlpacaClient` against `respx` fixtures recorded from Alpaca's documented
response shapes: a normal page, a multi-page response, a 429 with
`Retry-After`, and a snapshot missing a symbol."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from stockticker.ingest.alpaca.client import DATA_API_BASE_URL, TRADING_API_BASE_URL, AlpacaClient
from stockticker.ingest.http import reset_rate_budgets


@pytest.fixture(autouse=True)
def _reset_budgets() -> Iterator[None]:
    reset_rate_budgets()
    yield
    reset_rate_budgets()


def _client() -> AlpacaClient:
    return AlpacaClient("test-key", "test-secret")


@respx.mock
async def test_get_clock_parses_a_normal_response() -> None:
    respx.get(f"{TRADING_API_BASE_URL}/v2/clock").mock(
        return_value=httpx.Response(
            200,
            json={
                "timestamp": "2026-09-17T14:15:22Z",
                "is_open": True,
                "next_open": "2026-09-18T09:30:00-04:00",
                "next_close": "2026-09-17T16:00:00-04:00",
            },
        )
    )
    clock = await _client().get_clock()
    assert clock.is_open is True
    assert clock.next_open.year == 2026


@respx.mock
async def test_get_clock_is_cached_across_calls() -> None:
    route = respx.get(f"{TRADING_API_BASE_URL}/v2/clock").mock(
        return_value=httpx.Response(
            200,
            json={
                "timestamp": "2026-09-17T14:15:22Z",
                "is_open": False,
                "next_open": "2026-09-18T09:30:00-04:00",
                "next_close": "2026-09-17T16:00:00-04:00",
            },
        )
    )
    client = _client()
    await client.get_clock()
    await client.get_clock()
    assert route.call_count == 1


@respx.mock
async def test_get_calendar_combines_date_and_hhmm_into_ny_timestamps() -> None:
    respx.get(f"{TRADING_API_BASE_URL}/v2/calendar").mock(
        return_value=httpx.Response(
            200,
            json=[{"date": "2026-09-17", "open": "09:30", "close": "16:00", "settlement_date": "2026-09-19"}],
        )
    )
    days = await _client().get_calendar(date(2026, 9, 17), date(2026, 9, 17))
    assert len(days) == 1
    day = days[0]
    assert day.trade_date == date(2026, 9, 17)
    assert (day.open_at.hour, day.open_at.minute) == (9, 30)
    assert (day.close_at.hour, day.close_at.minute) == (16, 0)


@respx.mock
async def test_get_bars_single_page() -> None:
    respx.get(f"{DATA_API_BASE_URL}/v2/stocks/bars").mock(
        return_value=httpx.Response(
            200,
            json={
                "bars": {
                    "AAPL": [
                        {"t": "2026-01-02T05:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100},
                    ]
                },
                "next_page_token": None,
            },
        )
    )
    bars = await _client().get_bars(["AAPL"], date(2026, 1, 1), date(2026, 1, 5), adjustment="raw")
    assert [bar.close for bar in bars["AAPL"]] == [Decimal("1.5")]


@respx.mock
async def test_get_bars_follows_next_page_token_until_exhausted() -> None:
    route = respx.get(f"{DATA_API_BASE_URL}/v2/stocks/bars")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "bars": {"AAPL": [{"t": "2026-01-02T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]},
                "next_page_token": "page-2",
            },
        ),
        httpx.Response(
            200,
            json={
                "bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "o": 2, "h": 2, "l": 2, "c": 2, "v": 2}]},
                "next_page_token": None,
            },
        ),
    ]
    bars = await _client().get_bars(["AAPL"], date(2026, 1, 1), date(2026, 1, 10), adjustment="raw")
    assert [bar.trade_date for bar in bars["AAPL"]] == [date(2026, 1, 2), date(2026, 1, 5)]
    assert route.call_count == 2
    second_call_params = dict(httpx.QueryParams(route.calls[1].request.url.query))
    assert second_call_params["page_token"] == "page-2"


@respx.mock
async def test_get_bars_retries_on_429_honoring_retry_after() -> None:
    route = respx.get(f"{DATA_API_BASE_URL}/v2/stocks/bars")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "rate limited"}),
        httpx.Response(
            200,
            json={
                "bars": {"AAPL": [{"t": "2026-01-02T05:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]},
                "next_page_token": None,
            },
        ),
    ]
    bars = await _client().get_bars(["AAPL"], date(2026, 1, 1), date(2026, 1, 5), adjustment="raw")
    assert len(bars["AAPL"]) == 1
    assert route.call_count == 2


@respx.mock
async def test_get_snapshots_skips_a_symbol_missing_a_trade() -> None:
    respx.get(f"{DATA_API_BASE_URL}/v2/stocks/snapshots").mock(
        return_value=httpx.Response(
            200,
            json={
                "AAPL": {"latestTrade": {"t": "2026-09-17T14:00:00Z", "p": 230.5}},
                "MSFT": {"latestQuote": {"t": "2026-09-17T14:00:00Z", "bp": 1, "ap": 2}},
            },
        )
    )
    quotes = await _client().get_snapshots(["AAPL", "MSFT", "ZZZZ"], feed="iex")
    assert {quote.symbol for quote in quotes} == {"AAPL"}
    assert quotes[0].price == Decimal("230.5")


@respx.mock
async def test_get_snapshots_with_retry_false_does_not_retry_on_500() -> None:
    route = respx.get(f"{DATA_API_BASE_URL}/v2/stocks/snapshots").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await _client().get_snapshots(["AAPL"], feed="iex", retry=False)
    assert route.call_count == 1


@respx.mock
async def test_get_corporate_actions_parses_every_action_kind() -> None:
    respx.get(f"{DATA_API_BASE_URL}/v1/corporate-actions").mock(
        return_value=httpx.Response(
            200,
            json={
                "corporate_actions": {
                    "forward_splits": [
                        {
                            "id": "1",
                            "symbol": "AAPL",
                            "old_rate": "1",
                            "new_rate": "4",
                            "ex_date": "2026-08-31",
                        }
                    ],
                    "reverse_splits": [
                        {
                            "id": "2",
                            "symbol": "XYZ",
                            "old_rate": "10",
                            "new_rate": "1",
                            "ex_date": "2026-08-15",
                        }
                    ],
                    "cash_dividends": [
                        {"id": "3", "symbol": "AAPL", "rate": "0.24", "ex_date": "2026-08-10"}
                    ],
                    "name_changes": [
                        {"id": "4", "old_symbol": "FB", "new_symbol": "META", "process_date": "2022-06-09"}
                    ],
                },
                "next_page_token": None,
            },
        )
    )
    page = await _client().get_corporate_actions(
        ["AAPL", "XYZ", "FB"],
        types=("forward_split", "reverse_split", "cash_dividend", "name_change"),
        start=date(2018, 1, 1),
        end=date(2026, 9, 17),
    )
    assert page.splits[0].reverse is False
    assert page.splits[1].reverse is True
    assert page.dividends[0].rate == Decimal("0.24")
    assert page.name_changes[0].new_symbol == "META"
    assert page.errors == []


@respx.mock
async def test_get_corporate_actions_skips_one_malformed_row_not_the_whole_page() -> None:
    respx.get(f"{DATA_API_BASE_URL}/v1/corporate-actions").mock(
        return_value=httpx.Response(
            200,
            json={
                "corporate_actions": {
                    "forward_splits": [
                        {
                            "id": "1",
                            "symbol": "AAPL",
                            "old_rate": "1",
                            "new_rate": "4",
                            "ex_date": "2026-08-31",
                        },
                        {"id": "2", "symbol": "XYZ", "ex_date": "2026-08-15"},  # missing old_rate/new_rate
                    ],
                },
                "next_page_token": None,
            },
        )
    )
    page = await _client().get_corporate_actions(
        ["AAPL", "XYZ"], types=("forward_split",), start=date(2018, 1, 1), end=date(2026, 9, 17)
    )
    assert len(page.splits) == 1
    assert page.splits[0].symbol == "AAPL"
    assert len(page.errors) == 1
    assert "id=2" in page.errors[0]
