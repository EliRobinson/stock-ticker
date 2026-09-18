"""`corporate_actions_sync` (system design §4) against a real, migrated
Postgres: split/dividend/name-change events written with a stable
`source_ref`, a name change resolved through the *old* Listing's `cik`, and
an unknown symbol recorded as a failed item. See
tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import random
import string
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.alpaca.client import (
    CashDividendAction,
    CorporateActionsPage,
    NameChangeAction,
    SplitAction,
)
from stockticker.ingest.jobs.corporate_actions_sync import run_corporate_actions_sync


def _symbol() -> str:
    """A random *valid* ticker (letters only) -- `to_event` now validates
    the shape of a name change's symbols, so a hex-digit test fixture
    would fail that check rather than exercise the path under test."""
    return "T" + "".join(random.choices(string.ascii_uppercase, k=5))


class _FakeCorporateActionsClient:
    def __init__(self, page: CorporateActionsPage) -> None:
        self._page = page

    async def get_corporate_actions(
        self, symbols: Sequence[str], *, types: Sequence[str], start: date, end: date
    ) -> CorporateActionsPage:
        wanted = set(symbols)
        return CorporateActionsPage(
            splits=[a for a in self._page.splits if a.symbol in wanted],
            dividends=[a for a in self._page.dividends if a.symbol in wanted],
            name_changes=[a for a in self._page.name_changes if a.old_symbol in wanted],
        )


async def _make_listing(conn: AsyncConnection, symbol: str) -> str:
    cik = f"9{uuid.uuid4().int % 10**8:08d}"
    await conn.execute(
        text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test', 'Test')"), {"cik": cik}
    )
    await conn.execute(
        text("INSERT INTO listings (symbol, cik, is_primary, is_active) VALUES (:symbol, :cik, true, true)"),
        {"symbol": symbol, "cik": cik},
    )
    await conn.commit()
    return cik


async def _cleanup(engine: AsyncEngine, symbol: str, cik: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("DELETE FROM events WHERE cik = :cik"), {"cik": cik})
        await conn.execute(
            text("DELETE FROM ingest_watermarks WHERE job = 'corporate_actions_sync'"),
        )
        await conn.execute(text("DELETE FROM listings WHERE symbol = :symbol"), {"symbol": symbol})
        await conn.execute(text("DELETE FROM companies WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


async def test_corporate_actions_sync_writes_a_split_with_a_stable_source_ref(
    app_writer_engine: AsyncEngine,
) -> None:
    symbol = _symbol()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        page = CorporateActionsPage(
            splits=[
                SplitAction(
                    id="split-1",
                    symbol=symbol,
                    old_rate=Decimal("1"),
                    new_rate=Decimal("4"),
                    ex_date=date(2026, 8, 31),
                    reverse=False,
                )
            ],
            dividends=[],
            name_changes=[],
        )
        result = await run_corporate_actions_sync(app_writer_engine, _FakeCorporateActionsClient(page))
        assert result.rows_written == 1

        async with app_writer_engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT kind, event_date, source_ref FROM events WHERE cik = :cik"), {"cik": cik}
                )
            ).one()
            assert row.kind == "split"
            assert row.event_date == date(2026, 8, 31)
            assert row.source_ref == "split:split-1"

        # Idempotent: running again does not create a second row.
        await run_corporate_actions_sync(app_writer_engine, _FakeCorporateActionsClient(page))
        async with app_writer_engine.connect() as conn:
            count = (
                await conn.execute(text("SELECT count(*) FROM events WHERE cik = :cik"), {"cik": cik})
            ).scalar_one()
            assert count == 1
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_corporate_actions_sync_links_a_name_change_through_the_old_listing(
    app_writer_engine: AsyncEngine,
) -> None:
    old_symbol = _symbol()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, old_symbol)
    try:
        page = CorporateActionsPage(
            splits=[],
            dividends=[],
            name_changes=[
                NameChangeAction(
                    id="rename-1", old_symbol=old_symbol, new_symbol="NEWCO", process_date=date(2026, 6, 1)
                )
            ],
        )
        result = await run_corporate_actions_sync(app_writer_engine, _FakeCorporateActionsClient(page))
        assert result.rows_written == 1

        async with app_writer_engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT cik, kind, symbol FROM events WHERE source_ref = 'name_change:rename-1'")
                )
            ).one()
            assert row.cik == cik
            assert row.kind == "symbol_change"
            assert row.symbol == old_symbol
    finally:
        await _cleanup(app_writer_engine, old_symbol, cik)


class _AlwaysReturnsThisPageClient:
    """Unlike `_FakeCorporateActionsClient`, ignores the requested symbols --
    stands in for Alpaca returning an action for a symbol this DB has no
    Listing for (e.g. one whose corporate action predates our own
    `constituents_sync` picking it up)."""

    def __init__(self, page: CorporateActionsPage) -> None:
        self._page = page

    async def get_corporate_actions(
        self, symbols: Sequence[str], *, types: Sequence[str], start: date, end: date
    ) -> CorporateActionsPage:
        return self._page


async def test_corporate_actions_sync_records_an_unknown_symbol_as_a_failed_item(
    app_writer_engine: AsyncEngine,
) -> None:
    symbol = _symbol()
    unknown_symbol = _symbol()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        page = CorporateActionsPage(
            splits=[],
            dividends=[
                CashDividendAction(
                    id="div-1", symbol=unknown_symbol, rate=Decimal("0.24"), ex_date=date(2026, 7, 1)
                )
            ],
            name_changes=[],
        )
        result = await run_corporate_actions_sync(app_writer_engine, _AlwaysReturnsThisPageClient(page))
        assert result.rows_written == 0
        assert [item.key for item in result.failed_items] == [unknown_symbol]
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_corporate_actions_sync_writes_a_per_symbol_bootstrap_watermark(
    app_writer_engine: AsyncEngine,
) -> None:
    """Issue #4 review fix: the bootstrap watermark is per symbol
    (`bootstrapped:{symbol}`), not one global flag -- a Company added to
    the index later still gets its own full look-back."""
    symbol = _symbol()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, symbol)
    try:
        page = CorporateActionsPage(splits=[], dividends=[], name_changes=[])
        await run_corporate_actions_sync(app_writer_engine, _FakeCorporateActionsClient(page))

        async with app_writer_engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM ingest_watermarks WHERE job = 'corporate_actions_sync' AND key = :key"
                    ),
                    {"key": f"bootstrapped:{symbol}"},
                )
            ).first()
            assert row is not None
    finally:
        await _cleanup(app_writer_engine, symbol, cik)


async def test_corporate_actions_sync_resolves_a_name_change_through_an_inactive_listing(
    app_writer_engine: AsyncEngine,
) -> None:
    """Issue #4 review fix: `old_symbol` is looked up across every
    Listing, including inactive ones -- by the time a rename lands, the
    old Listing is usually already inactive."""
    old_symbol = _symbol()
    async with app_writer_engine.connect() as conn:
        cik = await _make_listing(conn, old_symbol)
        await conn.execute(text("UPDATE listings SET is_active = false WHERE symbol = :s"), {"s": old_symbol})
        await conn.commit()
    try:
        page = CorporateActionsPage(
            splits=[],
            dividends=[],
            name_changes=[
                NameChangeAction(
                    id="rename-2", old_symbol=old_symbol, new_symbol="NEWCOX", process_date=date(2026, 6, 1)
                )
            ],
        )
        result = await run_corporate_actions_sync(app_writer_engine, _AlwaysReturnsThisPageClient(page))
        assert result.rows_written == 1

        async with app_writer_engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT cik FROM events WHERE source_ref = 'name_change:rename-2'"))
            ).one()
            assert row.cik == cik
    finally:
        await _cleanup(app_writer_engine, old_symbol, cik)
