"""The Market Cap math (system design §3), run against Postgres because the
rebuild is one SQL statement per Company. Every test runs inside one
transaction that is rolled back, so nothing it writes is ever committed.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.edgar.parse import DEI_SHARES, US_GAAP_SHARES
from stockticker.ingest.market_caps import SplitRatioError, rebuild_company

ALPHABET = "0001652044"
BERKSHIRE = "0001067983"


@pytest_asyncio.fixture
async def conn(app_writer_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with app_writer_engine.connect() as connection:
        yield connection
        await connection.rollback()


def d(value: str) -> date:
    return date.fromisoformat(value)


class Scenario:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def company(self, cik: str | None = None) -> str:
        cik = cik or f"9{uuid.uuid4().int % 10**9:09d}"
        await self.conn.execute(
            text(
                "INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Test Co', 'Test') "
                "ON CONFLICT (cik) DO NOTHING"
            ),
            {"cik": cik},
        )
        return cik

    async def listing(
        self, cik: str, symbol: str | None = None, *, primary: bool = True, active: bool = True
    ) -> str:
        symbol = symbol or f"T{uuid.uuid4().hex[:6].upper()}"
        if primary and active:
            await self.conn.execute(
                text("UPDATE listings SET is_primary = false WHERE cik = :cik AND symbol <> :symbol"),
                {"cik": cik, "symbol": symbol},
            )
        await self.conn.execute(
            text(
                "INSERT INTO listings (symbol, cik, is_primary, is_active) "
                "VALUES (:symbol, :cik, :primary, :active) "
                "ON CONFLICT (symbol) DO UPDATE SET cik = excluded.cik, is_primary = excluded.is_primary, "
                "is_active = excluded.is_active"
            ),
            {"symbol": symbol, "cik": cik, "primary": primary, "active": active},
        )
        return symbol

    async def bars(self, symbol: str, closes: dict[str, str]) -> None:
        for day, close in closes.items():
            trade_date = d(day)
            opens = datetime.combine(trade_date, time(13, 30), tzinfo=UTC)
            await self.conn.execute(
                text(
                    "INSERT INTO trading_days (trade_date, open_at, close_at) VALUES (:d, :o, :c) "
                    "ON CONFLICT (trade_date) DO NOTHING"
                ),
                {"d": trade_date, "o": opens, "c": opens + timedelta(hours=6, minutes=30)},
            )
            await self.conn.execute(
                text(
                    "INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, adj_close, "
                    "source, ingested_at) VALUES (:s, :d, :p, :p, :p, :p, 0, :p, 'test', now()) "
                    "ON CONFLICT (symbol, trade_date) DO UPDATE SET open = excluded.open, "
                    "high = excluded.high, low = excluded.low, close = excluded.close, "
                    "adj_close = excluded.adj_close"
                ),
                {"s": symbol, "d": trade_date, "p": Decimal(close)},
            )

    async def shares(
        self,
        cik: str,
        as_of: str,
        filed: str,
        shares: int,
        *,
        concept: str = DEI_SHARES,
        accession: str | None = None,
    ) -> None:
        await self.conn.execute(
            text(
                "INSERT INTO shares_outstanding "
                "(cik, as_of_date, concept, accession, form, filed_date, shares) "
                "VALUES (:cik, :as_of, :concept, :accession, '10-Q', :filed, :shares)"
            ),
            {
                "cik": cik,
                "as_of": d(as_of),
                "concept": concept,
                "accession": accession or f"acc-{uuid.uuid4().hex[:10]}",
                "filed": d(filed),
                "shares": shares,
            },
        )

    async def event(
        self, cik: str, symbol: str | None, kind: str, on: str, details: dict[str, Any] | None = None
    ) -> None:
        await self.conn.execute(
            text(
                "INSERT INTO events (cik, symbol, event_date, kind, title, details, source, source_ref) "
                "VALUES (:cik, :symbol, :on, :kind, 'test', CAST(:details AS jsonb), 'test', :ref)"
            ),
            {
                "cik": cik,
                "symbol": symbol,
                "on": d(on),
                "kind": kind,
                "details": json.dumps(details or {}),
                "ref": uuid.uuid4().hex,
            },
        )

    async def caps(self, cik: str) -> dict[date, Any]:
        result = await self.conn.execute(
            text(
                "SELECT trade_date, market_cap, shares_used, shares_as_of, is_multi_class "
                "FROM market_caps WHERE cik = :cik ORDER BY trade_date"
            ),
            {"cik": cik},
        )
        return {row.trade_date: row for row in result}


@pytest_asyncio.fixture
async def s(conn: AsyncConnection) -> Scenario:
    return Scenario(conn)


async def test_single_class_company_is_close_times_latest_count(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2020-01-17", "2020-01-29", 1_000)
    await s.bars(symbol, {"2020-02-03": "10.50"})

    rebuilt = await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    row = caps[d("2020-02-03")]
    assert row.market_cap == Decimal("10500.00")
    assert row.shares_used == 1_000
    assert row.shares_as_of == d("2020-01-17")
    assert row.is_multi_class is False
    assert rebuilt.upserted == 1 and rebuilt.rejections == []


async def test_four_for_one_split_between_two_filings(s: Scenario) -> None:
    """Apple 2020: the last pre-split cover count (2020-07-17), a 4-for-1
    split with ex-date 2020-08-31, then the first post-split cover count."""
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2020-07-17", "2020-07-31", 4_275_634_000)
    await s.shares(cik, "2020-10-16", "2020-10-30", 17_001_802_000)
    await s.event(cik, symbol, "split", "2020-08-31", {"new_rate": 4, "old_rate": 1})
    await s.bars(
        symbol,
        {"2020-08-28": "499.23", "2020-08-31": "129.04", "2020-10-29": "115.32", "2020-10-30": "108.86"},
    )

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert caps[d("2020-08-28")].shares_used == 4_275_634_000
    assert caps[d("2020-08-31")].shares_used == 4 * 4_275_634_000
    assert caps[d("2020-10-29")].shares_used == 4 * 4_275_634_000
    assert caps[d("2020-10-30")].shares_used == 17_001_802_000
    assert caps[d("2020-08-31")].market_cap == Decimal("129.04") * 4 * 4_275_634_000
    assert caps[d("2020-10-30")].shares_as_of == d("2020-10-16")


async def test_reverse_split_divides_the_count(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2023-03-31", "2023-04-20", 50_000_000)
    await s.event(cik, symbol, "reverse_split", "2023-05-01", {"new_rate": 1, "old_rate": 10})
    await s.bars(symbol, {"2023-04-28": "2.00", "2023-05-01": "20.10"})

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert caps[d("2023-04-28")].shares_used == 50_000_000
    assert caps[d("2023-05-01")].shares_used == 5_000_000
    assert caps[d("2023-05-01")].market_cap == Decimal("100500000.00")


async def test_two_splits_compound(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2021-01-15", "2021-01-28", 1_000_000)
    await s.event(cik, symbol, "split", "2021-03-01", {"ratio": 2})
    await s.event(cik, symbol, "split", "2021-04-01", {"ratio": 3})
    await s.bars(symbol, {"2021-03-31": "1", "2021-04-01": "1"})

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert caps[d("2021-03-31")].shares_used == 2_000_000
    assert caps[d("2021-04-01")].shares_used == 6_000_000


async def test_a_split_on_another_listing_does_not_apply(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    old = await s.listing(cik, primary=False, active=False)
    await s.shares(cik, "2021-01-15", "2021-01-28", 1_000_000)
    await s.event(cik, old, "split", "2021-03-01", {"ratio": 2})
    await s.bars(symbol, {"2021-03-02": "1"})

    await rebuild_company(s.conn, cik)

    assert (await s.caps(cik))[d("2021-03-02")].shares_used == 1_000_000


async def test_alphabet_is_priced_on_googl_and_flagged_multi_class(s: Scenario) -> None:
    await s.company(ALPHABET)
    googl = await s.listing(ALPHABET, "GOOGL")
    goog = await s.listing(ALPHABET, "GOOG", primary=False)
    await s.shares(ALPHABET, "2023-09-30", "2023-10-24", 12_526_000_000, concept=US_GAAP_SHARES)
    await s.bars(googl, {"2023-11-01": "125.30"})
    await s.bars(goog, {"2023-11-01": "999.99"})

    await rebuild_company(s.conn, ALPHABET)

    row = (await s.caps(ALPHABET))[d("2023-11-01")]
    assert row.market_cap == Decimal("125.30") * 12_526_000_000
    assert row.shares_used == 12_526_000_000
    assert row.is_multi_class is True


async def test_berkshire_counts_class_a_equivalents_in_brk_b_units(s: Scenario) -> None:
    await s.company(BERKSHIRE)
    brk_b = await s.listing(BERKSHIRE, "BRK.B")
    await s.shares(BERKSHIRE, "2023-10-16", "2023-10-30", 1_440_000)
    await s.bars(brk_b, {"2023-11-01": "345.67"})

    await rebuild_company(s.conn, BERKSHIRE)

    row = (await s.caps(BERKSHIRE))[d("2023-11-01")]
    assert row.shares_used == 1_440_000 * 1500
    assert row.market_cap == Decimal("345.67") * 1_440_000 * 1500
    assert row.is_multi_class is True


async def test_ticker_change_prices_only_the_active_listing(s: Scenario) -> None:
    """FB -> META: the old Listing is inactive but still has bars. Its bars
    must neither price the Company nor double its value."""
    cik = await s.company()
    fb = await s.listing(cik, primary=False, active=False)
    meta = await s.listing(cik)
    await s.shares(cik, "2022-04-22", "2022-04-28", 2_700_000_000)
    await s.bars(fb, {"2022-06-08": "196.64", "2022-06-09": "196.64"})
    await s.bars(meta, {"2022-06-09": "184.00"})

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert list(caps) == [d("2022-06-09")]
    assert caps[d("2022-06-09")].market_cap == Decimal("184.00") * 2_700_000_000


async def test_no_active_price_listing_means_no_rows_and_old_rows_are_removed(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2022-04-22", "2022-04-28", 1_000)
    await s.bars(symbol, {"2022-06-09": "1"})
    await rebuild_company(s.conn, cik)
    assert len(await s.caps(cik)) == 1

    await s.conn.execute(text("UPDATE listings SET is_active = false WHERE symbol = :s"), {"s": symbol})
    rebuilt = await rebuild_company(s.conn, cik)

    assert await s.caps(cik) == {}
    assert rebuilt.removed == 1


async def test_tie_break_prefers_the_latest_filing_for_the_same_as_of_date(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2021-12-31", "2022-02-02", 1_000, concept=US_GAAP_SHARES)
    await s.shares(cik, "2021-12-31", "2022-04-27", 1_010, concept=US_GAAP_SHARES)
    await s.bars(symbol, {"2022-03-01": "1", "2022-05-02": "1"})

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert caps[d("2022-03-01")].shares_used == 1_000
    assert caps[d("2022-05-02")].shares_used == 1_010


async def test_tie_break_prefers_dei_over_us_gaap_for_the_same_date_and_filing(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2022-03-31", "2022-04-27", 2_000, concept=US_GAAP_SHARES, accession="same")
    await s.shares(cik, "2022-03-31", "2022-04-27", 2_020, concept=DEI_SHARES, accession="same")
    await s.bars(symbol, {"2022-05-02": "1"})

    await rebuild_company(s.conn, cik)

    assert (await s.caps(cik))[d("2022-05-02")].shares_used == 2_020


async def test_the_latest_filing_wins_over_a_later_as_of_date(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2022-04-15", "2022-04-27", 3_000, concept=DEI_SHARES)
    await s.shares(cik, "2022-03-31", "2022-04-29", 2_990, concept=US_GAAP_SHARES)
    await s.bars(symbol, {"2022-04-28": "1", "2022-05-02": "1"})

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert caps[d("2022-04-28")].shares_used == 3_000
    assert caps[d("2022-05-02")].shares_used == 2_990


async def test_within_one_filing_the_latest_as_of_date_wins(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2021-12-31", "2022-04-27", 1_000, concept=US_GAAP_SHARES, accession="q1")
    await s.shares(cik, "2022-03-31", "2022-04-27", 1_010, concept=US_GAAP_SHARES, accession="q1")
    await s.bars(symbol, {"2022-05-02": "1"})

    await rebuild_company(s.conn, cik)

    assert (await s.caps(cik))[d("2022-05-02")].shares_used == 1_010


async def test_a_split_between_the_cover_date_and_the_filing_applies_to_a_dei_count(s: Scenario) -> None:
    """A cover-page count is the number outstanding on its as_of_date, so a
    split after that day is still owed even though the filing came later."""
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2024-05-17", "2024-05-29", 2_464_000_000)
    await s.event(cik, symbol, "split", "2024-05-24", {"new_rate": 10, "old_rate": 1})
    await s.bars(symbol, {"2024-05-30": "110.50"})

    await rebuild_company(s.conn, cik)

    assert (await s.caps(cik))[d("2024-05-30")].shares_used == 24_640_000_000


async def test_berkshire_without_a_whole_company_count_gets_no_rows(s: Scenario) -> None:
    await s.company(BERKSHIRE)
    brk_b = await s.listing(BERKSHIRE, "BRK.B")
    await s.bars(brk_b, {"2023-11-01": "345.67"})

    rebuilt = await rebuild_company(s.conn, BERKSHIRE)

    assert await s.caps(BERKSHIRE) == {}
    assert rebuilt.no_whole_company_count is True
    assert rebuilt.rejections == []


async def test_brown_forman_is_seeded_as_multi_class_priced_on_bf_b(s: Scenario) -> None:
    rule = (
        await s.conn.execute(
            text("SELECT price_symbol, shares_unit_ratio FROM share_class_rules WHERE cik = '0000014693'")
        )
    ).one()
    assert (rule.price_symbol, rule.shares_unit_ratio) == ("BF.B", 1)

    bf_b = await s.listing("0000014693", "BF.B")
    await s.shares("0000014693", "2023-11-30", "2023-12-06", 473_000_000)
    await s.bars(bf_b, {"2023-12-07": "58.00"})

    await rebuild_company(s.conn, "0000014693")

    row = (await s.caps("0000014693"))[d("2023-12-07")]
    assert row.is_multi_class is True
    assert row.market_cap == Decimal("58.00") * 473_000_000


async def test_no_row_before_the_first_filing(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2017-12-29", "2018-02-01", 1_000)
    await s.bars(symbol, {"2018-01-02": "1", "2018-01-31": "1", "2018-02-01": "1"})

    await rebuild_company(s.conn, cik)

    assert list(await s.caps(cik)) == [d("2018-02-01")]


async def test_no_rows_at_all_without_a_filing(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.bars(symbol, {"2018-01-02": "1"})

    rebuilt = await rebuild_company(s.conn, cik)

    assert await s.caps(cik) == {}
    assert rebuilt.upserted == 0


async def test_rejected_count_after_its_filing_is_skipped_and_the_previous_carries(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2022-03-31", "2022-04-27", 1_000)
    await s.shares(cik, "2022-07-31", "2022-07-27", 1_050)
    await s.bars(symbol, {"2022-08-01": "1"})

    rebuilt = await rebuild_company(s.conn, cik)

    assert (await s.caps(cik))[d("2022-08-01")].shares_used == 1_000
    assert [r.reason for r in rebuilt.rejections] == [
        "count dated 2022-07-31, after its filing on 2022-07-27"
    ]


async def test_rejected_jump_is_skipped_and_the_previous_carries(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2022-03-31", "2022-04-27", 1_000_000)
    await s.shares(cik, "2022-06-30", "2022-07-27", 1_500_000)
    await s.bars(symbol, {"2022-08-01": "1"})

    rebuilt = await rebuild_company(s.conn, cik)

    assert (await s.caps(cik))[d("2022-08-01")].shares_used == 1_000_000
    assert len(rebuilt.rejections) == 1
    assert rebuilt.rejections[0].count.shares == 1_500_000


async def test_a_jump_is_accepted_when_a_spin_off_or_merger_is_in_between(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    other = await s.company()
    other_symbol = await s.listing(other)
    for company, listing in ((cik, symbol), (other, other_symbol)):
        await s.shares(company, "2022-03-31", "2022-04-27", 1_000_000)
        await s.shares(company, "2022-06-30", "2022-07-27", 1_500_000)
        await s.bars(listing, {"2022-08-01": "1"})
    await s.event(cik, symbol, "spin_off", "2022-05-15")
    await s.event(other, None, "filing_8k", "2022-05-15", {"items": ["2.01", "9.01"]})

    first = await rebuild_company(s.conn, cik)
    second = await rebuild_company(s.conn, other)

    assert first.rejections == [] and second.rejections == []
    assert (await s.caps(cik))[d("2022-08-01")].shares_used == 1_500_000
    assert (await s.caps(other))[d("2022-08-01")].shares_used == 1_500_000


async def test_a_split_without_a_usable_ratio_stops_the_rebuild(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.event(cik, symbol, "split", "2022-05-15", {"note": "no ratio"})

    with pytest.raises(SplitRatioError):
        await rebuild_company(s.conn, cik)


async def test_alphabet_2022_split_uses_only_counts_known_on_the_day(s: Scenario) -> None:
    """Real Alphabet counts around the 20-for-1 split (ex 2022-07-18). EDGAR
    re-reports the 2021-12-31 count post-split in filings from 2022-07-27 on.
    §3 as written would use that restated 13.2B count for early-2022 prices
    (the latest filing wins the tie-break) and multiply the restated
    2022-06-30 count by 20 again after the split: both ~20x too high."""
    cik = await s.company()
    symbol = await s.listing(cik)
    g = US_GAAP_SHARES
    await s.shares(cik, "2021-09-30", "2021-10-27", 664_682_000, concept=g)
    await s.shares(cik, "2021-12-31", "2022-02-02", 662_121_000, concept=g)
    await s.shares(cik, "2021-12-31", "2022-04-27", 662_121_000, concept=g, accession="q1")
    await s.shares(cik, "2022-03-31", "2022-04-27", 658_763_000, concept=g, accession="q1")
    await s.shares(cik, "2021-12-31", "2022-07-27", 13_242_000_000, concept=g, accession="q2")
    await s.shares(cik, "2022-06-30", "2022-07-27", 13_078_000_000, concept=g, accession="q2")
    await s.event(cik, symbol, "split", "2022-07-18", {"new_rate": 20, "old_rate": 1})
    await s.bars(
        symbol,
        {
            "2022-01-14": "2832.32",
            "2022-02-03": "2861.80",
            "2022-07-15": "2235.55",
            "2022-07-18": "109.03",
            "2022-07-28": "114.34",
        },
    )

    rebuilt = await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert rebuilt.rejections == []
    assert caps[d("2022-01-14")].shares_used == 664_682_000
    assert caps[d("2022-02-03")].shares_used == 662_121_000
    assert caps[d("2022-07-15")].shares_used == 658_763_000
    assert caps[d("2022-07-18")].shares_used == 20 * 658_763_000
    assert caps[d("2022-07-28")].shares_used == 13_078_000_000
    for row in caps.values():
        assert Decimal("1.3e12") < row.market_cap < Decimal("2.0e12")


async def test_apple_restated_comparative_does_not_leak_into_2019(s: Scenario) -> None:
    """Apple's 10-K filed 2020-10-30 restates the 2019-09-28 balance-sheet
    count post-split (17.77B). Before that filing the pre-split count holds."""
    cik = await s.company()
    symbol = await s.listing(cik)
    g = US_GAAP_SHARES
    await s.shares(cik, "2019-09-28", "2020-01-29", 4_443_236_000, concept=g)
    await s.shares(cik, "2019-09-28", "2020-10-30", 17_772_945_000, concept=g, accession="10-K 2020")
    await s.shares(cik, "2020-10-16", "2020-10-30", 17_001_802_000, accession="10-K 2020")
    await s.event(cik, symbol, "split", "2020-08-31", {"new_rate": 4, "old_rate": 1})
    await s.bars(symbol, {"2020-02-03": "308.66", "2020-09-01": "134.18", "2020-10-30": "108.86"})

    await rebuild_company(s.conn, cik)

    caps = await s.caps(cik)
    assert caps[d("2020-02-03")].shares_used == 4_443_236_000
    assert caps[d("2020-09-01")].shares_used == 4 * 4_443_236_000
    assert caps[d("2020-10-30")].shares_used == 17_001_802_000


async def test_rebuild_is_idempotent(s: Scenario) -> None:
    cik = await s.company()
    symbol = await s.listing(cik)
    await s.shares(cik, "2020-01-17", "2020-01-29", 1_000)
    await s.bars(symbol, {"2020-02-03": "1", "2020-02-04": "2"})

    first = await rebuild_company(s.conn, cik)
    second = await rebuild_company(s.conn, cik)

    assert (first.upserted, first.removed) == (2, 0)
    assert (second.upserted, second.removed) == (0, 0)
