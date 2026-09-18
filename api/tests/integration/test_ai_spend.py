"""The spend gate against a real ledger (`ai_usage`, migration 0002): the
limit boundary, the reservation, and two callers racing for the last room.
See tests/integration/conftest.py for how to run these.

The ledger is append-only for the app (no role but the superuser may delete
from it, and the test container has no superuser credentials), so every test
measures from the ledger's totals at its start: limits and budgets are the
baseline plus the amount under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ai.pricing import PRICES, TokenUsage
from stockticker.ai.spend import (
    DailyTokenBudgetReached,
    PostgresSpendLedger,
    SpendGate,
    SpendLimitReached,
)
from stockticker.ai.status import ai_status, typical_worst_case_usd
from stockticker.config import Settings, get_settings
from stockticker.db import dispose_engines
from stockticker.models.status import AiStatus

MODEL = "claude-sonnet-5"
LIMIT = Decimal("5.00")
DAY_START = datetime.now(UTC) - timedelta(hours=1)


@dataclass
class Books:
    ledger: PostgresSpendLedger
    base_spent: Decimal
    base_tokens: int

    def gate(self, limit: Decimal = LIMIT, daily_token_budget: int = 2_000_000) -> SpendGate:
        return SpendGate(
            limit_usd=self.base_spent + limit,
            daily_token_budget=self.base_tokens + daily_token_budget,
            day_start=DAY_START,
        )

    async def reserve(self, amount: str, *, daily_token_budget: int = 2_000_000) -> int:
        gate = self.gate(daily_token_budget=daily_token_budget)
        return await self.ledger.reserve(model=MODEL, worst_case_usd=Decimal(amount), gate=gate)

    async def spend(self, amount: str, usage: TokenUsage | None = None) -> None:
        reservation = await self.reserve(amount)
        await self.ledger.settle(reservation, usage=usage or TokenUsage(), cost_usd=Decimal(amount))

    async def spent(self) -> Decimal:
        return await self.ledger.spent_usd() - self.base_spent


@pytest_asyncio.fixture
async def books(app_writer_engine: AsyncEngine) -> AsyncIterator[Books]:
    ledger = PostgresSpendLedger(app_writer_engine)
    totals = await ledger.totals(DAY_START)
    yield Books(ledger, totals.spent_usd, totals.tokens_today)


async def test_spend_just_under_the_limit_allows_a_call_that_fits_exactly(books: Books) -> None:
    await books.spend("4.99")
    await books.reserve("0.01")
    assert await books.spent() == LIMIT


async def test_spend_exactly_at_the_limit_blocks_every_call(books: Books) -> None:
    await books.spend("5.00")
    with pytest.raises(SpendLimitReached):
        await books.reserve("0.000001")


async def test_a_reservation_that_would_go_over_is_refused_and_not_recorded(books: Books) -> None:
    await books.spend("4.90")
    with pytest.raises(SpendLimitReached):
        await books.reserve("0.100001")
    assert await books.spent() == Decimal("4.90")


async def test_the_limit_message_names_the_configured_limit(books: Books) -> None:
    gate = SpendGate(limit_usd=Decimal("0"), daily_token_budget=10**12, day_start=DAY_START)
    with pytest.raises(SpendLimitReached, match=r"^AI spend limit reached \(\$0\.00\)\. Raise AI_SPEND"):
        await books.ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate)


async def test_open_reservations_count_against_the_limit(books: Books) -> None:
    await books.reserve("3")
    with pytest.raises(SpendLimitReached):
        await books.reserve("3")


async def test_settling_replaces_the_reservation_with_the_actual_cost(books: Books) -> None:
    reservation = await books.reserve("0.33")
    await books.ledger.settle(
        reservation,
        usage=TokenUsage(input_tokens=1000, cache_read_input_tokens=200, output_tokens=50),
        cost_usd=Decimal("0.002540"),
    )
    assert await books.spent() == Decimal("0.002540")


async def test_concurrent_callers_cannot_both_take_the_last_room(books: Books) -> None:
    await books.spend("4.00")

    async def attempt() -> bool:
        try:
            await books.reserve("0.30")
        except SpendLimitReached:
            return False
        return True

    outcomes = await asyncio.gather(*(attempt() for _ in range(10)))
    assert outcomes.count(True) == 3  # 4.00 + 3 x 0.30 = 4.90; a fourth would be 5.20
    assert await books.spent() == Decimal("4.90")


async def test_daily_token_budget(books: Books) -> None:
    await books.spend("0.01", TokenUsage(input_tokens=1_000))
    with pytest.raises(DailyTokenBudgetReached):
        await books.reserve("0.01", daily_token_budget=1_000)
    await books.reserve("0.01", daily_token_budget=1_001)


async def test_the_daily_token_sum_counts_every_kind_of_token(books: Books) -> None:
    usage = TokenUsage(
        input_tokens=1, cache_creation_input_tokens=20, cache_read_input_tokens=300, output_tokens=4_000
    )
    await books.spend("0.01", usage)
    with pytest.raises(DailyTokenBudgetReached):
        await books.reserve("0.01", daily_token_budget=usage.total_tokens)
    await books.reserve("0.01", daily_token_budget=usage.total_tokens + 1)


async def test_app_writer_cannot_erase_spend(app_writer_engine: AsyncEngine, books: Books) -> None:
    await books.spend("1.00")
    async with app_writer_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(text("DELETE FROM ai_usage"))


async def test_stale_reservations_expire_at_their_reserved_cost(
    books: Books, app_writer_engine: AsyncEngine
) -> None:
    stale = await books.reserve("0.40")
    async with app_writer_engine.begin() as conn:
        await conn.execute(
            text("UPDATE ai_usage SET created_at = now() - interval '11 minutes' WHERE id = :id"),
            {"id": stale},
        )
    fresh = await books.reserve("0.10")
    async with app_writer_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, state, cost_usd FROM ai_usage WHERE id IN (:stale, :fresh) ORDER BY id"),
                {"stale": stale, "fresh": fresh},
            )
        ).all()
    assert [(row.state, row.cost_usd) for row in rows] == [
        ("expired", Decimal("0.400000")),
        ("reserved", Decimal("0.100000")),
    ]
    assert await books.spent() == Decimal("0.50")  # expired is not refunded


# --- /status ----------------------------------------------------------------


@pytest_asyncio.fixture
async def app_engines() -> AsyncIterator[None]:
    """`ai_status` and the app use the process-wide engines; each test has
    its own event loop, so they are disposed after every test."""
    yield
    await dispose_engines()


def _settings(books: Books, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "anthropic_api_key": "test-key",
        "ai_model": MODEL,
        "ai_spend_limit_usd": books.base_spent + LIMIT,
    }
    values.update(overrides)
    return get_settings().model_copy(update=values)


async def test_ai_status_reports_spend_and_is_enabled_with_room(books: Books, app_engines: None) -> None:
    await books.spend("1.25")
    status = await ai_status(_settings(books))
    assert status == AiStatus(
        spend_usd=float(books.base_spent + Decimal("1.25")),
        limit_usd=float(books.base_spent + LIMIT),
        enabled=True,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"anthropic_api_key": None},
        {"ai_model": "claude-unpriced-9"},
        {"spend_room": Decimal("0.05")},
    ],
)
async def test_ai_status_fails_closed(books: Books, app_engines: None, overrides: dict[str, object]) -> None:
    await books.spend("1.25")
    room = overrides.pop("spend_room", None)
    if isinstance(room, Decimal):
        overrides["ai_spend_limit_usd"] = books.base_spent + Decimal("1.25") + room
    status = await ai_status(_settings(books, **overrides))
    assert status.enabled is False


async def test_ai_status_is_disabled_when_a_typical_call_would_not_fit(
    books: Books, app_engines: None
) -> None:
    await books.spend(str(LIMIT - typical_worst_case_usd(PRICES[MODEL]) + Decimal("0.000001")))
    assert (await ai_status(_settings(books))).enabled is False


async def test_status_serves_the_ai_block(
    books: Books, app_engines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await books.spend("1.25")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_SPEND_LIMIT_USD", str(books.base_spent + LIMIT))
    get_settings.cache_clear()
    from stockticker.api.app import create_app

    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.get("/api/v1/status")
        assert response.status_code == 200
        assert response.json()["ai"] == {
            "spend_usd": pytest.approx(float(books.base_spent + Decimal("1.25"))),
            "limit_usd": pytest.approx(float(books.base_spent + LIMIT)),
            "enabled": True,
        }
    finally:
        get_settings.cache_clear()
