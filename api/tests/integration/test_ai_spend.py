"""The spend gate against a real ledger (`ai_usage`, migration 0002): the
limit boundary, the reservation, and two callers racing for the last room.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Defined once in test_ai_reader_role until tests/integration/conftest.py
# (the foundation's) gains a shared `superuser_engine` fixture.
from test_ai_reader_role import superuser_engine  # noqa: E402, F401

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


def gate(limit: Decimal = LIMIT, daily_token_budget: int = 2_000_000) -> SpendGate:
    return SpendGate(
        limit_usd=limit,
        daily_token_budget=daily_token_budget,
        day_start=datetime.now(UTC) - timedelta(hours=1),
    )


@pytest_asyncio.fixture
async def ledger(
    app_writer_engine: AsyncEngine,
    superuser_engine: AsyncEngine,  # noqa: F811 -- the fixture imported above
) -> AsyncIterator[PostgresSpendLedger]:
    # app_writer cannot delete from the ledger (by design), so the superuser
    # empties it around each test.
    async with superuser_engine.begin() as conn:
        await conn.execute(text("TRUNCATE ai_usage"))
    yield PostgresSpendLedger(app_writer_engine)
    async with superuser_engine.begin() as conn:
        await conn.execute(text("TRUNCATE ai_usage"))


async def spend(ledger: PostgresSpendLedger, amount: str, tokens: int = 0) -> None:
    reservation = await ledger.reserve(model=MODEL, worst_case_usd=Decimal(amount), gate=gate())
    await ledger.settle(reservation, usage=TokenUsage(input_tokens=tokens), cost_usd=Decimal(amount))


async def test_spend_just_under_the_limit_allows_a_call_that_fits_exactly(
    ledger: PostgresSpendLedger,
) -> None:
    await spend(ledger, "4.99")
    await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate())
    assert await ledger.spent_usd() == LIMIT


async def test_spend_exactly_at_the_limit_blocks_every_call(ledger: PostgresSpendLedger) -> None:
    await spend(ledger, "5.00")
    with pytest.raises(SpendLimitReached, match=r"AI spend limit reached \(\$5\.00\)"):
        await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.000001"), gate=gate())


async def test_a_reservation_that_would_go_over_is_refused_and_not_recorded(
    ledger: PostgresSpendLedger,
) -> None:
    await spend(ledger, "4.90")
    with pytest.raises(SpendLimitReached):
        await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.100001"), gate=gate())
    assert await ledger.spent_usd() == Decimal("4.90")


async def test_open_reservations_count_against_the_limit(ledger: PostgresSpendLedger) -> None:
    await ledger.reserve(model=MODEL, worst_case_usd=Decimal("3"), gate=gate())
    with pytest.raises(SpendLimitReached):
        await ledger.reserve(model=MODEL, worst_case_usd=Decimal("3"), gate=gate())


async def test_settling_replaces_the_reservation_with_the_actual_cost(ledger: PostgresSpendLedger) -> None:
    reservation = await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.33"), gate=gate())
    await ledger.settle(
        reservation,
        usage=TokenUsage(input_tokens=1000, cache_read_input_tokens=200, output_tokens=50),
        cost_usd=Decimal("0.002540"),
    )
    assert await ledger.spent_usd() == Decimal("0.002540")


async def test_concurrent_callers_cannot_both_take_the_last_room(ledger: PostgresSpendLedger) -> None:
    await spend(ledger, "4.00")

    async def attempt() -> bool:
        try:
            await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.30"), gate=gate())
        except SpendLimitReached:
            return False
        return True

    outcomes = await asyncio.gather(*(attempt() for _ in range(10)))
    assert outcomes.count(True) == 3  # 4.00 + 3 x 0.30 = 4.90; a fourth would be 5.20
    assert await ledger.spent_usd() == Decimal("4.90")


async def test_daily_token_budget(ledger: PostgresSpendLedger) -> None:
    await spend(ledger, "0.01", tokens=1_000)
    with pytest.raises(DailyTokenBudgetReached, match="1,000 tokens"):
        await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate(daily_token_budget=1_000))
    await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate(daily_token_budget=1_001))


async def test_the_daily_token_sum_counts_every_kind_of_token(ledger: PostgresSpendLedger) -> None:
    usage = TokenUsage(
        input_tokens=1, cache_creation_input_tokens=20, cache_read_input_tokens=300, output_tokens=4_000
    )
    reservation = await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate())
    await ledger.settle(reservation, usage=usage, cost_usd=Decimal("0.01"))
    with pytest.raises(DailyTokenBudgetReached):
        await ledger.reserve(
            model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate(daily_token_budget=usage.total_tokens)
        )
    await ledger.reserve(
        model=MODEL, worst_case_usd=Decimal("0.01"), gate=gate(daily_token_budget=usage.total_tokens + 1)
    )


async def test_app_writer_cannot_erase_spend(
    app_writer_engine: AsyncEngine, ledger: PostgresSpendLedger
) -> None:
    await spend(ledger, "1.00")
    async with app_writer_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(text("DELETE FROM ai_usage"))


async def test_stale_reservations_expire_at_their_reserved_cost(
    ledger: PostgresSpendLedger,
    superuser_engine: AsyncEngine,  # noqa: F811 -- the fixture imported above
) -> None:
    await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.40"), gate=gate())
    async with superuser_engine.begin() as conn:
        await conn.execute(text("UPDATE ai_usage SET created_at = now() - interval '11 minutes'"))
    await ledger.reserve(model=MODEL, worst_case_usd=Decimal("0.10"), gate=gate())
    async with superuser_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT state, cost_usd FROM ai_usage ORDER BY id"))).all()
    assert [(row.state, row.cost_usd) for row in rows] == [
        ("expired", Decimal("0.400000")),
        ("reserved", Decimal("0.100000")),
    ]
    assert await ledger.spent_usd() == Decimal("0.50")  # expired is not refunded


@pytest_asyncio.fixture
async def app_engines() -> AsyncIterator[None]:
    """`ai_status` and the app use the process-wide engines; each test has
    its own event loop, so they are disposed after every test."""
    yield
    await dispose_engines()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"anthropic_api_key": "test-key", "ai_model": MODEL}
    values.update(overrides)
    return get_settings().model_copy(update=values)


async def test_ai_status_reports_spend_and_is_enabled_with_room(
    ledger: PostgresSpendLedger, app_engines: None
) -> None:
    await spend(ledger, "1.25")
    status = await ai_status(_settings())
    assert status == AiStatus(spend_usd=1.25, limit_usd=5.0, enabled=True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"anthropic_api_key": None},
        {"ai_model": "claude-unpriced-9"},
        {"ai_spend_limit_usd": Decimal("1.30")},
    ],
)
async def test_ai_status_fails_closed(
    ledger: PostgresSpendLedger, app_engines: None, overrides: dict[str, object]
) -> None:
    await spend(ledger, "1.25")
    status = await ai_status(_settings(**overrides))
    assert status.enabled is False
    assert status.spend_usd == 1.25


async def test_ai_status_is_disabled_when_a_typical_call_would_not_fit(
    ledger: PostgresSpendLedger, app_engines: None
) -> None:
    limit = Decimal("5.00")
    await spend(ledger, str(limit - typical_worst_case_usd(PRICES[MODEL]) + Decimal("0.000001")))
    assert (await ai_status(_settings(ai_spend_limit_usd=limit))).enabled is False


async def test_status_reports_ai_spend(
    ledger: PostgresSpendLedger, app_engines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await spend(ledger, "1.25")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    from stockticker.api.app import create_app
    from stockticker.db import dispose_engines

    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.get("/api/v1/status")
        assert response.status_code == 200
        assert response.json()["ai"] == {"spend_usd": 1.25, "limit_usd": 5.0, "enabled": True}
    finally:
        await dispose_engines()
        get_settings.cache_clear()
