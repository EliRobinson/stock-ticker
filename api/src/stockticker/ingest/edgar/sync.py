"""`edgar_sync` (system design §4): shares outstanding from `companyfacts`,
10-K/10-Q/8-K Events from `submissions`, for every active Company.

The host is fixed to `data.sec.gov`, every call draws from the `sec` rate
budget (5 req/s), and the `User-Agent` comes from `SEC_USER_AGENT`. No
transaction is open while a request is in flight: each Company is fetched
first, then written and committed on its own.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.config import RequiredKey
from stockticker.ingest.edgar.parse import (
    FilingEvent,
    SharesFact,
    cik_path,
    parse_filings,
    parse_shares,
)
from stockticker.ingest.http import RateBudgetName, build_http_client, request
from stockticker.ingest.job import ConfigMissingError, FailedItem, JobContext, JobResult, JobSkipped
from stockticker.logging import get_logger

logger = get_logger(__name__)

EDGAR_BASE_URL = "https://data.sec.gov"
EVENT_SOURCE = "sec"


def build_edgar_client(user_agent: str) -> httpx.AsyncClient:
    return build_http_client(base_url=EDGAR_BASE_URL, headers={"User-Agent": user_agent})


async def fetch_companyfacts(client: httpx.AsyncClient, cik: str) -> dict[str, Any] | None:
    """`None` when EDGAR has no XBRL facts for the CIK (404)."""
    try:
        response = await request(
            client, "GET", f"/api/xbrl/companyfacts/{cik_path(cik)}.json", rate_budget=RateBudgetName.SEC
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise
    data: dict[str, Any] = response.json()
    return data


async def fetch_submissions(client: httpx.AsyncClient, cik: str) -> dict[str, Any]:
    response = await request(
        client, "GET", f"/submissions/{cik_path(cik)}.json", rate_budget=RateBudgetName.SEC
    )
    data: dict[str, Any] = response.json()
    return data


async def run_edgar_sync(engine: AsyncEngine, *, user_agent: str) -> JobResult:
    async with engine.connect() as conn:
        companies = await _active_companies(conn)
        await conn.rollback()
    if not companies:
        raise JobSkipped("no active Companies")

    result = JobResult()
    async with build_edgar_client(user_agent) as client:
        for cik, symbol in companies:
            try:
                companyfacts = await fetch_companyfacts(client, cik)
                submissions = await fetch_submissions(client, cik)
            except httpx.HTTPError as exc:
                result.failed_items.append(FailedItem(key=cik, error=f"EDGAR request failed: {exc}"))
                continue

            if companyfacts is None:
                shares: list[SharesFact] = []
                result.failed_items.append(
                    FailedItem(key=cik, error="EDGAR has no companyfacts for this CIK")
                )
            else:
                parsed = parse_shares(companyfacts)
                shares = parsed.facts
                result.failed_items.extend(
                    FailedItem(key=f"{cik}:{key}", error=reason) for key, reason in parsed.rejected
                )
            filings = parse_filings(submissions, cik)

            async with engine.connect() as conn:
                result.rows_written += await store_edgar_company(conn, cik, symbol, shares, filings)
                await conn.commit()
            logger.debug("edgar_sync.company", cik=cik, shares=len(shares), filings=len(filings))
    return result


async def edgar_sync(ctx: JobContext) -> JobResult:
    user_agent = ctx.settings.sec_user_agent
    if not user_agent:  # registry's requires_keys already checks; this narrows the type
        raise ConfigMissingError([RequiredKey.SEC_USER_AGENT.value])
    return await run_edgar_sync(ctx.engine, user_agent=user_agent)


async def _active_companies(conn: AsyncConnection) -> list[tuple[str, str | None]]:
    result = await conn.execute(
        text(
            "SELECT c.cik, l.symbol FROM companies c "
            "LEFT JOIN listings l ON l.cik = c.cik AND l.is_primary AND l.is_active "
            "WHERE c.is_active ORDER BY c.cik"
        )
    )
    return [(row.cik, row.symbol) for row in result]


async def store_edgar_company(
    conn: AsyncConnection,
    cik: str,
    symbol: str | None,
    shares: Sequence[SharesFact],
    filings: Sequence[FilingEvent],
) -> int:
    """Upsert one Company's shares and filing Events. Does not commit."""
    written = 0
    if shares:
        result = await conn.execute(
            text(
                "INSERT INTO shares_outstanding "
                "(cik, as_of_date, concept, accession, form, filed_date, shares) "
                "SELECT :cik, * FROM unnest("
                "CAST(:as_of AS date[]), CAST(:concept AS text[]), CAST(:accession AS text[]), "
                "CAST(:form AS text[]), CAST(:filed AS date[]), CAST(:shares AS bigint[])) "
                "ON CONFLICT (cik, as_of_date, concept, accession) DO UPDATE SET "
                "form = excluded.form, filed_date = excluded.filed_date, shares = excluded.shares "
                "WHERE (shares_outstanding.form, shares_outstanding.filed_date, shares_outstanding.shares) "
                "IS DISTINCT FROM (excluded.form, excluded.filed_date, excluded.shares)"
            ),
            {
                "cik": cik,
                "as_of": [fact.as_of_date for fact in shares],
                "concept": [fact.concept for fact in shares],
                "accession": [fact.accession for fact in shares],
                "form": [fact.form for fact in shares],
                "filed": [fact.filed_date for fact in shares],
                "shares": [fact.shares for fact in shares],
            },
        )
        written += result.rowcount or 0
    if filings:
        result = await conn.execute(
            text(
                "INSERT INTO events (cik, symbol, event_date, kind, title, details, source, source_ref) "
                "SELECT :cik, :symbol, e.event_date, e.kind, e.title, e.details, :source, e.accession "
                "FROM unnest(CAST(:event_date AS date[]), CAST(:kind AS text[]), CAST(:title AS text[]), "
                "CAST(:details AS jsonb[]), CAST(:accession AS text[])) "
                "AS e(event_date, kind, title, details, accession) "
                "ON CONFLICT (source, source_ref) DO UPDATE SET "
                "event_date = excluded.event_date, kind = excluded.kind, title = excluded.title, "
                "details = excluded.details, symbol = COALESCE(excluded.symbol, events.symbol) "
                "WHERE (events.event_date, events.kind, events.title, events.details) "
                "IS DISTINCT FROM (excluded.event_date, excluded.kind, excluded.title, excluded.details)"
            ),
            {
                "cik": cik,
                "symbol": symbol,
                "source": EVENT_SOURCE,
                "event_date": [event.event_date for event in filings],
                "kind": [event.kind for event in filings],
                "title": [event.title for event in filings],
                "details": [json.dumps(event.details) for event in filings],
                "accession": [event.accession for event in filings],
            },
        )
        written += result.rowcount or 0
    return written
