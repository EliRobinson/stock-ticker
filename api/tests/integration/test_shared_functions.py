"""`public.prev_trading_day` and `public.price_symbol` (migration 0001):
the two rules that were getting written twice, once per branch, with the
copies disagreeing. See tests/integration/conftest.py for how to run
these."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _seed_trading_day(app_writer_engine: AsyncEngine, trade_date: date) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO trading_days (trade_date, open_at, close_at) "
                "VALUES (:d, :open_at, :close_at) ON CONFLICT DO NOTHING"
            ),
            {
                "d": trade_date,
                "open_at": datetime.combine(trade_date, time(14, 30), tzinfo=UTC),
                "close_at": datetime.combine(trade_date, time(21, 0), tzinfo=UTC),
            },
        )
        await conn.commit()


async def _prev_trading_day(app_writer_engine: AsyncEngine, anchor: date) -> date | None:
    async with app_writer_engine.connect() as conn:
        value: date | None = await conn.scalar(
            text("SELECT public.prev_trading_day(:anchor)"), {"anchor": anchor}
        )
        return value


async def test_prev_trading_day_returns_the_latest_day_strictly_before_anchor(
    app_writer_engine: AsyncEngine,
) -> None:
    # trading_days rows are never deleted (shared, append-only across the
    # whole suite) -- a date range no other test in this file touches, so
    # an unrelated test's seeded day can't change these results.
    await _seed_trading_day(app_writer_engine, date(2024, 11, 4))
    await _seed_trading_day(app_writer_engine, date(2024, 11, 5))
    await _seed_trading_day(app_writer_engine, date(2024, 11, 6))

    assert await _prev_trading_day(app_writer_engine, date(2024, 11, 6)) == date(2024, 11, 5)
    assert await _prev_trading_day(app_writer_engine, date(2024, 11, 5)) == date(2024, 11, 4)


async def test_prev_trading_day_is_null_when_nothing_precedes_anchor(app_writer_engine: AsyncEngine) -> None:
    # No trading_days seed needed or wanted here: an anchor this far in the
    # past is guaranteed to have nothing before it, regardless of what any
    # other test in the shared, append-only trading_days table has seeded.
    assert await _prev_trading_day(app_writer_engine, date(1900, 1, 1)) is None


async def test_prev_trading_day_skips_a_gap_to_the_next_earlier_trading_day(
    app_writer_engine: AsyncEngine,
) -> None:
    """The function itself always finds *a* trading day (there's no such
    thing as a missing trading_days row for a real trading day, only a
    missing daily_bars row) -- ai.quotes is what turns "the exact prior
    day has no bar" into null, by joining daily_bars on this result
    without any further fallback."""
    # trading_days rows are never deleted (shared, append-only across the
    # whole suite) -- a date range no other test in this file touches,
    # so an unrelated test's seeded day can't land in this "gap".
    await _seed_trading_day(app_writer_engine, date(2024, 12, 2))
    await _seed_trading_day(app_writer_engine, date(2024, 12, 16))
    assert await _prev_trading_day(app_writer_engine, date(2024, 12, 16)) == date(2024, 12, 2)


async def _seed_company_and_listing(
    app_writer_engine: AsyncEngine, cik: str, symbol: str, *, is_primary: bool, is_active: bool
) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test') "
                "ON CONFLICT (cik) DO NOTHING"
            ),
            {"cik": cik},
        )
        await conn.execute(
            text(
                "INSERT INTO listings (symbol, cik, is_primary, is_active) "
                "VALUES (:symbol, :cik, :is_primary, :is_active)"
            ),
            {"symbol": symbol, "cik": cik, "is_primary": is_primary, "is_active": is_active},
        )
        await conn.commit()


async def _price_symbol(app_writer_engine: AsyncEngine, cik: str) -> str | None:
    async with app_writer_engine.connect() as conn:
        value: str | None = await conn.scalar(text("SELECT public.price_symbol(:cik)"), {"cik": cik})
        return value


async def _cleanup(app_writer_engine: AsyncEngine, cik: str) -> None:
    async with app_writer_engine.connect() as conn:
        await conn.execute(text("DELETE FROM share_class_rules WHERE cik = :cik"), {"cik": cik})
        await conn.execute(text("DELETE FROM listings WHERE cik = :cik"), {"cik": cik})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def test_price_symbol_uses_the_seeded_rule_when_that_listing_is_active(
    app_writer_engine: AsyncEngine,
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    class_a = f"T{uuid.uuid4().hex[:5].upper()}A"
    class_b = f"T{uuid.uuid4().hex[:5].upper()}B"
    try:
        await _seed_company_and_listing(app_writer_engine, cik, class_a, is_primary=True, is_active=True)
        await _seed_company_and_listing(app_writer_engine, cik, class_b, is_primary=False, is_active=True)
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO share_class_rules (cik, price_symbol, shares_unit_ratio, note) "
                    "VALUES (:cik, :symbol, 1, 'test')"
                ),
                {"cik": cik, "symbol": class_b},
            )
            await conn.commit()

        assert await _price_symbol(app_writer_engine, cik) == class_b
    finally:
        await _cleanup(app_writer_engine, cik)


async def test_price_symbol_falls_back_to_active_primary_when_the_seeded_symbol_is_inactive(
    app_writer_engine: AsyncEngine,
) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    primary = f"T{uuid.uuid4().hex[:5].upper()}A"
    delisted_class_b = f"T{uuid.uuid4().hex[:5].upper()}B"
    try:
        await _seed_company_and_listing(app_writer_engine, cik, primary, is_primary=True, is_active=True)
        await _seed_company_and_listing(
            app_writer_engine, cik, delisted_class_b, is_primary=False, is_active=False
        )
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO share_class_rules (cik, price_symbol, shares_unit_ratio, note) "
                    "VALUES (:cik, :symbol, 1, 'test')"
                ),
                {"cik": cik, "symbol": delisted_class_b},
            )
            await conn.commit()

        assert await _price_symbol(app_writer_engine, cik) == primary
    finally:
        await _cleanup(app_writer_engine, cik)


async def test_price_symbol_uses_active_primary_with_no_seeded_rule(app_writer_engine: AsyncEngine) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    primary = f"T{uuid.uuid4().hex[:6].upper()}"
    try:
        await _seed_company_and_listing(app_writer_engine, cik, primary, is_primary=True, is_active=True)
        assert await _price_symbol(app_writer_engine, cik) == primary
    finally:
        await _cleanup(app_writer_engine, cik)


async def test_price_symbol_is_null_with_no_active_listing_at_all(app_writer_engine: AsyncEngine) -> None:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    delisted = f"T{uuid.uuid4().hex[:6].upper()}"
    try:
        await _seed_company_and_listing(app_writer_engine, cik, delisted, is_primary=True, is_active=False)
        assert await _price_symbol(app_writer_engine, cik) is None
    finally:
        await _cleanup(app_writer_engine, cik)


async def test_price_symbol_is_null_for_an_unknown_cik(app_writer_engine: AsyncEngine) -> None:
    unknown_cik = f"9{uuid.uuid4().int % 10**8:08d}"
    assert await _price_symbol(app_writer_engine, unknown_cik) is None
