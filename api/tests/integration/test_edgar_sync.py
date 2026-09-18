"""`edgar_sync` end to end against Postgres, with EDGAR mocked by respx.
Unlike the other ingest tests this one commits (the job commits per
Company), so it uses a fresh random CIK and deletes what it wrote.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
import respx
from edgar_support import load_fixture as _fixture
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.edgar.sync import EDGAR_BASE_URL, run_edgar_sync
from stockticker.ingest.http import reset_rate_budgets

USER_AGENT = "Jane Doe jane@example.com"


@pytest.fixture(autouse=True)
def _reset_budgets() -> Iterator[None]:
    reset_rate_budgets()
    yield
    reset_rate_budgets()


@pytest_asyncio.fixture
async def company(app_writer_engine: AsyncEngine) -> AsyncIterator[tuple[str, str]]:
    cik = f"7{uuid.uuid4().int % 10**9:09d}"
    symbol = f"E{uuid.uuid4().hex[:6].upper()}"
    async with app_writer_engine.connect() as conn:
        await conn.execute(
            text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Edgar Co', 'Test')"), {"cik": cik}
        )
        await conn.execute(
            text("INSERT INTO listings (symbol, cik, is_primary, is_active) VALUES (:s, :cik, true, true)"),
            {"s": symbol, "cik": cik},
        )
        await conn.commit()
    yield cik, symbol
    async with app_writer_engine.connect() as conn:
        for table in ("events", "shares_outstanding", "listings", "companies"):
            await conn.execute(text(f"DELETE FROM {table} WHERE cik = :cik"), {"cik": cik})
        await conn.commit()


def _mock_edgar(cik: str, companyfacts: httpx.Response, submissions: httpx.Response) -> None:
    respx.get(f"{EDGAR_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json").mock(return_value=companyfacts)
    respx.get(f"{EDGAR_BASE_URL}/submissions/CIK{cik}.json").mock(return_value=submissions)


@respx.mock
async def test_edgar_sync_stores_shares_and_filing_events(
    app_writer_engine: AsyncEngine, company: tuple[str, str]
) -> None:
    cik, symbol = company
    _mock_edgar(
        cik,
        httpx.Response(200, json=_fixture("companyfacts_aapl.json")),
        httpx.Response(200, json=_fixture("submissions_aapl.json")),
    )

    result = await run_edgar_sync(app_writer_engine, user_agent=USER_AGENT, ciks=[cik])

    assert result.failed_items == []
    async with app_writer_engine.connect() as conn:
        shares = await conn.scalar(text("SELECT count(*) FROM shares_outstanding WHERE cik = :c"), {"c": cik})
        events = (
            await conn.execute(
                text("SELECT kind, symbol, title, details FROM events WHERE cik = :c ORDER BY event_date"),
                {"c": cik},
            )
        ).all()
    assert shares == 15
    assert [event.kind for event in events] == ["filing_10k", "filing_8k", "filing_8k", "filing_10q"]
    assert {event.symbol for event in events} == {symbol}
    earnings = events[2]
    assert earnings.title == "Results of operations (8-K)"
    assert earnings.details["accession"] == "0000320193-26-000018"
    assert earnings.details["url"].endswith("/000032019326000018/aapl-20260730.htm")

    again = await run_edgar_sync(app_writer_engine, user_agent=USER_AGENT, ciks=[cik])
    assert again.failed_items == []
    async with app_writer_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM events WHERE cik = :c"), {"c": cik}) == 4


@respx.mock
async def test_edgar_sync_records_a_failed_item_and_keeps_going(
    app_writer_engine: AsyncEngine, company: tuple[str, str]
) -> None:
    cik, _ = company
    _mock_edgar(cik, httpx.Response(404), httpx.Response(200, json=_fixture("submissions_aapl.json")))

    result = await run_edgar_sync(app_writer_engine, user_agent=USER_AGENT, ciks=[cik])

    mine = [item for item in result.failed_items if item.key == cik]
    assert [item.error for item in mine] == ["EDGAR has no companyfacts for this CIK"]
    async with app_writer_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM events WHERE cik = :c"), {"c": cik}) == 4


@respx.mock
async def test_a_malformed_body_is_one_failed_item_not_a_failed_run(
    app_writer_engine: AsyncEngine, company: tuple[str, str]
) -> None:
    cik, _ = company
    _mock_edgar(
        cik,
        httpx.Response(200, text="<html>rate limited</html>"),
        httpx.Response(200, json=_fixture("submissions_aapl.json")),
    )

    result = await run_edgar_sync(app_writer_engine, user_agent=USER_AGENT, ciks=[cik])

    assert [item.key for item in result.failed_items] == [cik]
    assert result.failed_items[0].error.startswith("EDGAR fetch or parse failed")
