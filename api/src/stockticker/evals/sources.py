"""The database side of a run: reference rows and the spend ledger's rows."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ai.executor import SqlExecutor
from stockticker.ai.guard import guard_sql
from stockticker.evals.runner import UsageRow


class GuardedReferenceSource:
    """Runs reference SQL exactly the way `run_sql` runs the model's: through
    the SQL guard, as `ai_reader`, read-only, with the same timeouts. So a
    reference can only use what the model can, and never writes."""

    def __init__(self, executor: SqlExecutor) -> None:
        self._executor = executor

    async def rows(self, sql: str) -> list[dict[str, Any]]:
        result = await self._executor.execute(guard_sql(sql).wrapped_sql)
        names = [column.name for column in result.columns]
        return [dict(zip(names, row, strict=True)) for row in result.rows]


class LedgerUsageSource:
    """Reads the `ai_usage` rows added since a watermark (as `app_writer`,
    which owns the ledger; `ai_reader` cannot see it)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def watermark(self) -> int:
        async with self._engine.connect() as conn:
            value = await conn.scalar(text("SELECT coalesce(max(id), 0) FROM ai_usage"))
        return int(value or 0)

    async def since(self, watermark: int) -> list[UsageRow]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT model, input_tokens, cache_creation_input_tokens, cache_read_input_tokens, "
                    "output_tokens, cost_usd FROM ai_usage WHERE id > :watermark ORDER BY id"
                ),
                {"watermark": watermark},
            )
            return [
                UsageRow(
                    model=row.model,
                    input_tokens=row.input_tokens or 0,
                    cache_creation_input_tokens=row.cache_creation_input_tokens or 0,
                    cache_read_input_tokens=row.cache_read_input_tokens or 0,
                    output_tokens=row.output_tokens or 0,
                    cost_usd=Decimal(row.cost_usd or 0),
                )
                for row in result
            ]
