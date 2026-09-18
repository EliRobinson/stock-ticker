"""The Anthropic spend ledger and the gate in front of every model call.

`AI_SPEND_LIMIT_USD` caps what the key may ever spend, in total. Before each
call, `reserve()` takes a transaction-scoped advisory lock, sums `ai_usage`
(settled calls plus reservations still in flight), and inserts a reservation
for the call's worst-case cost only if that still fits under the limit. Two
browser tabs therefore can never both pass the check with room for one.
`settle()` then replaces the reservation with the cost of the usage the SDK
reported. A reservation that is never settled (the process died mid-call)
keeps its worst-case cost, so the ledger errs high, never low.

`AI_DAILY_TOKEN_BUDGET` is checked in the same transaction, against tokens
recorded since midnight New York time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ai.pricing import TokenUsage

# Above the int4 range, so it can never equal a job wrapper lock
# (`pg_try_advisory_lock(hashtext(job))`, an int4 widened to bigint).
SPEND_LOCK_KEY = 0x61695F7370656E64  # "ai_spend"


class SpendGateError(Exception):
    """The call must not be made. `str(error)` is the user-facing message."""


class SpendLimitReached(SpendGateError):
    def __init__(self, limit_usd: Decimal) -> None:
        super().__init__(f"AI spend limit reached (${limit_usd:.2f}). Raise AI_SPEND_LIMIT_USD to continue.")


class DailyTokenBudgetReached(SpendGateError):
    def __init__(self, budget: int) -> None:
        super().__init__(
            f"Today's AI token budget ({budget:,} tokens) is used up, so AI is off until midnight "
            "New York time. Raise AI_DAILY_TOKEN_BUDGET to continue sooner."
        )


@dataclass(frozen=True)
class SpendGate:
    limit_usd: Decimal
    daily_token_budget: int
    day_start: datetime
    """Midnight New York time, today."""


class SpendLedger(Protocol):
    async def reserve(self, *, model: str, worst_case_usd: Decimal, gate: SpendGate) -> int: ...

    async def settle(self, reservation_id: int, *, usage: TokenUsage, cost_usd: Decimal) -> None: ...

    async def spent_usd(self) -> Decimal: ...


class PostgresSpendLedger:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def reserve(self, *, model: str, worst_case_usd: Decimal, gate: SpendGate) -> int:
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SPEND_LOCK_KEY})
            totals = (
                await conn.execute(
                    text(
                        "SELECT coalesce(sum(cost_usd), 0) AS spent, "
                        "coalesce(sum(input_tokens + cache_creation_input_tokens + cache_read_input_tokens "
                        "  + output_tokens) FILTER (WHERE created_at >= :day_start), 0) AS tokens_today "
                        "FROM ai_usage"
                    ),
                    {"day_start": gate.day_start},
                )
            ).one()
            if Decimal(totals.spent) + worst_case_usd > gate.limit_usd:
                raise SpendLimitReached(gate.limit_usd)
            if int(totals.tokens_today) >= gate.daily_token_budget:
                raise DailyTokenBudgetReached(gate.daily_token_budget)
            reservation_id = await conn.scalar(
                text(
                    "INSERT INTO ai_usage (model, state, cost_usd) "
                    "VALUES (:model, 'reserved', :cost) RETURNING id"
                ),
                {"model": model, "cost": worst_case_usd},
            )
        assert isinstance(reservation_id, int)
        return reservation_id

    async def settle(self, reservation_id: int, *, usage: TokenUsage, cost_usd: Decimal) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE ai_usage SET state = 'recorded', input_tokens = :input, "
                    "cache_creation_input_tokens = :cache_write, cache_read_input_tokens = :cache_read, "
                    "output_tokens = :output, cost_usd = :cost, settled_at = now() WHERE id = :id"
                ),
                {
                    "id": reservation_id,
                    "input": usage.input_tokens,
                    "cache_write": usage.cache_creation_input_tokens,
                    "cache_read": usage.cache_read_input_tokens,
                    "output": usage.output_tokens,
                    "cost": cost_usd,
                },
            )

    async def spent_usd(self) -> Decimal:
        async with self._engine.connect() as conn:
            spent = await conn.scalar(text("SELECT coalesce(sum(cost_usd), 0) FROM ai_usage"))
        return Decimal(spent)
