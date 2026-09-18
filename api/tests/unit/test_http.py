from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from stockticker.ingest.http import (
    RATE_BUDGETS,
    RateBudgetName,
    build_http_client,
    request,
    reset_rate_budgets,
)


@pytest.fixture(autouse=True)
def _reset_budgets() -> Iterator[None]:
    reset_rate_budgets()
    yield
    reset_rate_budgets()


def test_rate_budgets_match_the_documented_limits() -> None:
    assert RATE_BUDGETS[RateBudgetName.ALPACA_QUOTES].capacity == 40
    assert RATE_BUDGETS[RateBudgetName.ALPACA_QUOTES].per_seconds == 60.0
    assert RATE_BUDGETS[RateBudgetName.ALPACA].capacity == 100
    assert RATE_BUDGETS[RateBudgetName.SEC].capacity == 5
    assert RATE_BUDGETS[RateBudgetName.SEC].per_seconds == 1.0


@respx.mock
async def test_request_retries_on_5xx_then_succeeds() -> None:
    route = respx.get("https://example.test/ok").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )
    async with build_http_client(base_url="https://example.test") as client:
        response = await request(client, "GET", "/ok", rate_budget=RateBudgetName.SEC)
    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_request_does_not_retry_plain_4xx() -> None:
    respx.get("https://example.test/bad").mock(return_value=httpx.Response(400))
    async with build_http_client(base_url="https://example.test") as client:
        with pytest.raises(httpx.HTTPStatusError):
            await request(client, "GET", "/bad", rate_budget=RateBudgetName.SEC)


@respx.mock
async def test_request_gives_up_after_max_attempts() -> None:
    route = respx.get("https://example.test/always-503").mock(return_value=httpx.Response(503))
    async with build_http_client(base_url="https://example.test") as client:
        with pytest.raises(Exception, match="retryable status"):
            await request(client, "GET", "/always-503", rate_budget=RateBudgetName.SEC)
    assert route.call_count == 4
