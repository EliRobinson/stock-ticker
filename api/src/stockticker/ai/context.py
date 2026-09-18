"""Wires the Ask loop to the running app: the Anthropic client, the ai_reader
executor, the spend ledger, and the per-request prompt context."""

from __future__ import annotations

from datetime import datetime, time
from functools import lru_cache

from anthropic import AsyncAnthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ai.executor import AiReaderExecutor
from stockticker.ai.loop import ChatDeps, PromptContext
from stockticker.ai.prompt import build_system_prompt, market_status_line
from stockticker.ai.schema_prompt import schema_cache
from stockticker.ai.spend import PostgresSpendLedger
from stockticker.config import Settings
from stockticker.db import get_ai_reader_engine, get_api_app_writer_engine
from stockticker.marketdata import fetch_market_clock
from stockticker.timeutil import NY_TZ, now_ny

ANTHROPIC_TIMEOUT_SECONDS = 60.0


@lru_cache
def _anthropic_client(api_key: str) -> AsyncAnthropic:
    # Our own loop does the single retry the design allows (loop.py).
    return AsyncAnthropic(api_key=api_key, max_retries=0, timeout=ANTHROPIC_TIMEOUT_SECONDS)


@lru_cache
def _executor(engine: AsyncEngine) -> AiReaderExecutor:
    return AiReaderExecutor(engine)


def midnight_ny() -> datetime:
    return datetime.combine(now_ny().date(), time.min, tzinfo=NY_TZ)


async def market_status(engine: AsyncEngine, now: datetime) -> str:
    clock = await fetch_market_clock()
    if clock is not None:
        if clock.is_open:
            return f"open (closes {clock.next_close.astimezone(NY_TZ):%H:%M} New York time)"
        return f"closed (next open {clock.next_open.astimezone(NY_TZ):%Y-%m-%d %H:%M} New York time)"
    async with engine.connect() as conn:
        session = (
            await conn.execute(
                text("SELECT open_at, close_at FROM ai.trading_days WHERE trade_date = :today"),
                {"today": now.date()},
            )
        ).first()
        has_calendar = bool(
            await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM ai.trading_days WHERE trade_date >= :today)"),
                {"today": now.date()},
            )
        )
    return market_status_line(
        now=now,
        session=(session.open_at, session.close_at) if session is not None else None,
        has_calendar=has_calendar,
    )


async def load_prompt_context() -> PromptContext:
    engine = get_ai_reader_engine()
    catalog = await schema_cache.get(engine)
    now = now_ny()
    status = await market_status(engine, now)
    return PromptContext(
        system=build_system_prompt(catalog, today=now.date(), now=now, market_status=status),
        surface=catalog.surface,
    )


def build_chat_deps(settings: Settings) -> ChatDeps:
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    return ChatDeps(
        model=settings.ai_model,
        client=_anthropic_client(key) if key else None,
        executor=_executor(get_ai_reader_engine()),
        ledger=PostgresSpendLedger(get_api_app_writer_engine()),
        load_context=load_prompt_context,
        spend_limit_usd=settings.ai_spend_limit_usd,
        daily_token_budget=settings.ai_daily_token_budget,
        day_start=midnight_ny,
    )
