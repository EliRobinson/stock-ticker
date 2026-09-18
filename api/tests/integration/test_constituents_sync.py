"""`constituents_sync` against Postgres, with the real (trimmed) Wikipedia
table as input. Each test runs in one transaction that is rolled back; it
first marks every existing Company and Listing inactive inside that
transaction, so the deactivation rules only see what the test sets up.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.wikipedia.parser import ConstituentRow, parse_constituents
from stockticker.ingest.wikipedia.sync import (
    MAX_DEACTIVATIONS_PER_RUN,
    TooManyDeactivationsError,
    apply_constituents,
)

PAGE = (Path(__file__).parent.parent / "fixtures" / "wikipedia" / "sp500_constituents.html").read_text()
ROWS = parse_constituents(PAGE)


@pytest_asyncio.fixture
async def conn(app_writer_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with app_writer_engine.connect() as connection:
        await connection.execute(text("UPDATE listings SET is_active = false WHERE is_active"))
        await connection.execute(text("UPDATE companies SET is_active = false WHERE is_active"))
        await connection.execute(text("DELETE FROM ingest_watermarks WHERE job = 'constituents_sync'"))
        yield connection
        await connection.rollback()


async def _active(conn: AsyncConnection, table: str, key: str) -> set[str]:
    result = await conn.execute(text(f"SELECT {key} FROM {table} WHERE is_active"))
    return set(result.scalars())


def _without(symbols: set[str]) -> list[ConstituentRow]:
    return [row for row in ROWS if row.symbol not in symbols]


async def test_first_sync_loads_every_company_and_listing(conn: AsyncConnection) -> None:
    summary = await apply_constituents(conn, ROWS)

    ciks = {row.cik for row in ROWS}
    assert await _active(conn, "listings", "symbol") == {row.symbol for row in ROWS}
    assert await _active(conn, "companies", "cik") == ciks
    assert summary.companies_upserted == len(ciks)
    assert summary.listings_upserted == 503
    assert summary.companies_deactivated == summary.listings_deactivated == 0


async def test_one_primary_listing_per_company_following_share_class_rules(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS)

    per_company = await conn.execute(
        text(
            "SELECT l.cik, count(*) FILTER (WHERE l.is_primary) AS primaries FROM listings l "
            "WHERE l.is_active GROUP BY l.cik"
        )
    )
    assert {row.primaries for row in per_company} == {1}
    primaries = await conn.execute(
        text("SELECT symbol FROM listings WHERE is_active AND is_primary AND symbol = ANY(:s)"),
        {"s": ["GOOGL", "GOOG", "FOXA", "FOX", "NWSA", "NWS", "BRK.B"]},
    )
    assert set(primaries.scalars()) == {"GOOGL", "FOXA", "NWSA", "BRK.B"}


async def test_company_fields_come_from_the_table(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS)

    alphabet = (await conn.execute(text("SELECT * FROM companies WHERE cik = '0001652044'"))).one()
    assert alphabet.name == "Alphabet Inc."
    assert alphabet.sector == "Communication Services"
    assert str(alphabet.date_added) == "2006-04-03"


async def test_new_listings_start_without_a_completed_backfill(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS)

    pending = await conn.scalar(
        text("SELECT count(*) FROM listings WHERE is_active AND backfill_completed_at IS NULL")
    )
    assert pending == 503


async def test_existing_backfill_state_survives_a_resync(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS)
    await conn.execute(text("UPDATE listings SET backfill_completed_at = now() WHERE symbol = 'MMM'"))

    await apply_constituents(conn, ROWS)

    assert await conn.scalar(
        text("SELECT backfill_completed_at IS NOT NULL FROM listings WHERE symbol = 'MMM'")
    )


async def test_index_added_events_one_per_company_date(conn: AsyncConnection) -> None:
    summary = await apply_constituents(conn, ROWS)

    events = await conn.execute(
        text(
            "SELECT symbol, event_date, title, source_ref FROM events "
            "WHERE source = 'wikipedia' AND kind = 'index_added' AND cik = '0001652044' ORDER BY event_date"
        )
    )
    assert [(row.symbol, str(row.event_date), row.source_ref) for row in events] == [
        ("GOOGL", "2006-04-03", "0001652044:2006-04-03"),
        ("GOOG", "2014-04-03", "0001652044:2014-04-03"),
    ]
    fox = await conn.execute(
        text("SELECT symbol FROM events WHERE source = 'wikipedia' AND cik = '0001754301'")
    )
    assert list(fox.scalars()) == ["FOXA"]
    assert summary.events_written > 0

    again = await apply_constituents(conn, ROWS)
    assert again.events_written == 0


def day(n: int) -> date:
    return date(2026, 3, n)


async def test_missing_on_one_day_stays_active_missing_on_two_days_is_deactivated(
    conn: AsyncConnection,
) -> None:
    await apply_constituents(conn, ROWS, today=day(1))
    gone = {"MMM", "AOS"}

    first = await apply_constituents(conn, _without(gone), today=day(2))
    assert gone <= await _active(conn, "listings", "symbol")
    assert first.listings_deactivated == 0

    second = await apply_constituents(conn, _without(gone), today=day(3))
    assert not gone & await _active(conn, "listings", "symbol")
    assert not {"0000066740", "0000091142"} & await _active(conn, "companies", "cik")
    assert (second.companies_deactivated, second.listings_deactivated) == (2, 2)


async def test_several_runs_on_one_day_count_as_one_miss(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS, today=day(1))

    for _ in range(3):
        summary = await apply_constituents(conn, _without({"MMM"}), today=day(2))

    assert "MMM" in await _active(conn, "listings", "symbol")
    assert summary.listings_deactivated == 0


async def test_the_first_sync_deactivates_nothing(conn: AsyncConnection) -> None:
    await conn.execute(
        text("INSERT INTO companies (cik, name, sector) VALUES ('9999999901', 'Gone Co', 'Test')")
    )

    summary = await apply_constituents(conn, ROWS, today=day(1))

    assert summary.companies_deactivated == 0
    assert "9999999901" in await _active(conn, "companies", "cik")


async def test_reappearing_resets_the_miss(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS, today=day(1))
    await apply_constituents(conn, _without({"MMM"}), today=day(2))
    await apply_constituents(conn, ROWS, today=day(3))

    await apply_constituents(conn, _without({"MMM"}), today=day(4))

    assert "MMM" in await _active(conn, "listings", "symbol")


async def test_a_deactivated_company_comes_back_when_listed_again(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS, today=day(1))
    await apply_constituents(conn, _without({"MMM"}), today=day(2))
    await apply_constituents(conn, _without({"MMM"}), today=day(3))
    assert "MMM" not in await _active(conn, "listings", "symbol")

    await apply_constituents(conn, ROWS, today=day(4))

    assert "MMM" in await _active(conn, "listings", "symbol")
    assert "0000066740" in await _active(conn, "companies", "cik")


async def test_a_ticker_change_moves_the_primary_and_retires_the_old_listing(conn: AsyncConnection) -> None:
    renamed = [dataclasses.replace(row, symbol="MMMX") if row.symbol == "MMM" else row for row in ROWS]
    await apply_constituents(conn, ROWS, today=day(1))

    await apply_constituents(conn, renamed, today=day(2))
    primary = await conn.scalar(
        text("SELECT symbol FROM listings WHERE cik = '0000066740' AND is_primary AND is_active")
    )
    assert primary == "MMMX"
    assert "MMM" in await _active(conn, "listings", "symbol")

    await apply_constituents(conn, renamed, today=day(3))
    assert "MMM" not in await _active(conn, "listings", "symbol")
    assert "0000066740" in await _active(conn, "companies", "cik")


async def test_ten_company_deactivations_are_allowed(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS, today=day(1))
    gone = {row.symbol for row in ROWS[:MAX_DEACTIVATIONS_PER_RUN]}
    await apply_constituents(conn, _without(gone), today=day(2))

    summary = await apply_constituents(conn, _without(gone), today=day(3))

    assert summary.companies_deactivated == MAX_DEACTIVATIONS_PER_RUN


async def test_more_than_ten_company_deactivations_fail_the_run(conn: AsyncConnection) -> None:
    await apply_constituents(conn, ROWS, today=day(1))
    gone = {row.symbol for row in ROWS[: MAX_DEACTIVATIONS_PER_RUN + 1]}
    await apply_constituents(conn, _without(gone), today=day(2))

    with pytest.raises(TooManyDeactivationsError) as raised:
        await apply_constituents(conn, _without(gone), today=day(3))

    assert raised.value.table == "Companies"
    assert len(raised.value.keys) == MAX_DEACTIVATIONS_PER_RUN + 1


async def test_more_than_ten_listing_deactivations_fail_the_run(conn: AsyncConnection) -> None:
    """Eleven active Listings of one listed Company, absent from both the
    day-1 and day-2 lists: no Company would go, but the Listing cap trips."""
    await apply_constituents(conn, ROWS, today=day(1))
    extra = [f"ZZ{n:02d}" for n in range(MAX_DEACTIVATIONS_PER_RUN + 1)]
    for symbol in extra:
        await conn.execute(
            text(
                "INSERT INTO listings (symbol, cik, is_primary, is_active) "
                "VALUES (:s, '0000066740', false, true)"
            ),
            {"s": symbol},
        )

    with pytest.raises(TooManyDeactivationsError) as raised:
        await apply_constituents(conn, ROWS, today=day(2))

    assert raised.value.table == "Listings"
    assert raised.value.keys == extra


async def test_duplicate_symbols_are_rejected(conn: AsyncConnection) -> None:
    with pytest.raises(ValueError, match="MMM appears twice"):
        await apply_constituents(conn, [*ROWS, ROWS[0]])
