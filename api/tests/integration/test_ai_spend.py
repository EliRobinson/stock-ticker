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
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stockticker.ai.pricing import TokenUsage
from stockticker.ai.spend import (
    DailyTokenBudgetReached,
    PostgresSpendLedger,
    SpendGate,
    SpendLimitReached,
)
from stockticker.config import get_settings

LIMIT = Decimal("5.00")


def gate(limit: Decimal = LIMIT, daily_token_budget: int = 2_000_000) -> SpendGate:
    return SpendGate(
        limit_usd=limit,
        daily_token_budget=daily_token_budget,
        day_start=datetime.now(UTC) - timedelta(hours=1),
    )


@pytest_asyncio.fixture
async def ledger(app_writer_engine: AsyncEngine) -> AsyncIterator[PostgresSpendLedger]:
    # app_writer cannot delete from the ledger (by design), so the superuser
    # empties it around each test.
    superuser = create_async_engine(get_settings().superuser_dsn)
    try:
        async with superuser.begin() as conn:
            await conn.execute(text("TRUNCATE ai_usage"))
        yield PostgresSpendLedger(app_writer_engine)
        async with superuser.begin() as conn:
            await conn.execute(text("TRUNCATE ai_usage"))
    finally:
        await superuser.dispose()


async def spend(ledger: PostgresSpendLedger, amount: str, tokens: int = 0) -> None:
    reservation = await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal(amount), gate=gate())
    await ledger.settle(reservation, usage=TokenUsage(input_tokens=tokens), cost_usd=Decimal(amount))


async def test_spend_just_under_the_limit_allows_a_call_that_fits_exactly(
    ledger: PostgresSpendLedger,
) -> None:
    await spend(ledger, "4.99")
    await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("0.01"), gate=gate())
    assert await ledger.spent_usd() == LIMIT


async def test_spend_exactly_at_the_limit_blocks_every_call(ledger: PostgresSpendLedger) -> None:
    await spend(ledger, "5.00")
    with pytest.raises(SpendLimitReached, match=r"AI spend limit reached \(\$5\.00\)"):
        await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("0.000001"), gate=gate())


async def test_a_reservation_that_would_go_over_is_refused_and_not_recorded(
    ledger: PostgresSpendLedger,
) -> None:
    await spend(ledger, "4.90")
    with pytest.raises(SpendLimitReached):
        await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("0.100001"), gate=gate())
    assert await ledger.spent_usd() == Decimal("4.90")


async def test_open_reservations_count_against_the_limit(ledger: PostgresSpendLedger) -> None:
    await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("3"), gate=gate())
    with pytest.raises(SpendLimitReached):
        await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("3"), gate=gate())


async def test_settling_replaces_the_reservation_with_the_actual_cost(ledger: PostgresSpendLedger) -> None:
    reservation = await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("0.33"), gate=gate())
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
            await ledger.reserve(model="claude-sonnet-5", worst_case_usd=Decimal("0.30"), gate=gate())
        except SpendLimitReached:
            return False
        return True

    outcomes = await asyncio.gather(*(attempt() for _ in range(10)))
    assert outcomes.count(True) == 3  # 4.00 + 3 x 0.30 = 4.90; a fourth would be 5.20
    assert await ledger.spent_usd() == Decimal("4.90")


async def test_daily_token_budget(ledger: PostgresSpendLedger) -> None:
    await spend(ledger, "0.01", tokens=1_000)
    with pytest.raises(DailyTokenBudgetReached, match="1,000 tokens"):
        await ledger.reserve(
            model="claude-sonnet-5", worst_case_usd=Decimal("0.01"), gate=gate(daily_token_budget=1_000)
        )
    await ledger.reserve(
        model="claude-sonnet-5", worst_case_usd=Decimal("0.01"), gate=gate(daily_token_budget=1_001)
    )


async def test_app_writer_cannot_erase_spend(
    app_writer_engine: AsyncEngine, ledger: PostgresSpendLedger
) -> None:
    await spend(ledger, "1.00")
    async with app_writer_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(text("DELETE FROM ai_usage"))


async def test_status_reports_ai_spend(ledger: PostgresSpendLedger, monkeypatch: pytest.MonkeyPatch) -> None:
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
