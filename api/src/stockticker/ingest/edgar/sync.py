"""`edgar_sync` (system design §4): shares outstanding from `companyfacts`,
10-K/10-Q/8-K Events from `submissions` (plus the `files[]` pages that
reach 2018), for every active Company.

The host is fixed to `data.sec.gov`, every call draws from the `sec` rate
budget (5 req/s), and the `User-Agent` comes from `SEC_USER_AGENT`. No
transaction is open while a request is in flight: each Company is fetched
and parsed first, then written and committed on its own. A Company whose
fetch or parse fails is one failed item; the run moves on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.config import RequiredKey
from stockticker.ingest.edgar.parse import (
    FilingEvent,
    SharesFact,
    cik_path,
    older_filing_pages,
    parse_filings,
    parse_filings_page,
    parse_shares,
)
from stockticker.ingest.http import RateBudgetName, build_http_client, request
from stockticker.ingest.job import ConfigMissingError, FailedItem, JobContext, JobResult, JobSkipped
from stockticker.ingest.sinks import EventRow, upsert_events
from stockticker.logging import get_logger

logger = get_logger(__name__)

EDGAR_BASE_URL = "https://data.sec.gov"
EVENT_SOURCE = "sec"
NO_COMPANYFACTS = "EDGAR has no companyfacts for this CIK"


def build_edgar_client(user_agent: str) -> httpx.AsyncClient:
    return build_http_client(base_url=EDGAR_BASE_URL, headers={"User-Agent": user_agent})


async def _get_json(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    """GET one EDGAR document. Raises `httpx.HTTPError` for a failed request
    and `ValueError` for a body that is not a JSON object."""
    response = await request(client, "GET", path, rate_budget=RateBudgetName.SEC)
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object, got {type(data).__name__}")
    return data


@dataclass(slots=True)
class CompanyDocuments:
    shares: list[SharesFact] = field(default_factory=list)
    filings: list[FilingEvent] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    has_companyfacts: bool = True


async def fetch_company(client: httpx.AsyncClient, cik: str) -> CompanyDocuments:
    """Fetch and parse one Company's share counts and filing Events."""
    documents = CompanyDocuments()
    try:
        companyfacts = await _get_json(client, f"/api/xbrl/companyfacts/{cik_path(cik)}.json")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        documents.has_companyfacts = False
    else:
        parsed = parse_shares(companyfacts)
        documents.shares, documents.rejected = parsed.facts, parsed.rejected
    documents.filings = await fetch_filings(client, cik)
    return documents


async def fetch_filings(client: httpx.AsyncClient, cik: str) -> list[FilingEvent]:
    """Filing Events from `filings.recent` plus every `files[]` page that
    reaches 2018, one per accession."""
    submissions = await _get_json(client, f"/submissions/{cik_path(cik)}.json")
    events = parse_filings(submissions, cik)
    for name in older_filing_pages(submissions):
        events.extend(parse_filings_page(await _get_json(client, f"/submissions/{name}"), cik))
    by_accession = {event.accession: event for event in reversed(events)}
    return sorted(by_accession.values(), key=lambda event: (event.event_date, event.accession))


async def edgar_sync(ctx: JobContext) -> JobResult:
    user_agent = ctx.settings.sec_user_agent
    if not user_agent:  # registry's requires_keys already checks; this narrows the type
        raise ConfigMissingError([RequiredKey.SEC_USER_AGENT.value])
    return await run_edgar_sync(ctx.engine, user_agent=user_agent)


async def run_edgar_sync(
    engine: AsyncEngine, *, user_agent: str, ciks: Sequence[str] | None = None
) -> JobResult:
    """Sync every active Company, or only those of `ciks` that are active."""
    async with engine.connect() as conn:
        companies = await _active_companies(conn, ciks)
    if not companies:
        raise JobSkipped("no active Companies")

    result = JobResult()
    async with build_edgar_client(user_agent) as client:
        for cik, symbol in companies:
            try:
                documents = await fetch_company(client, cik)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
                result.failed_items.append(FailedItem(key=cik, error=f"EDGAR fetch or parse failed: {exc}"))
                continue
            if not documents.has_companyfacts:
                result.failed_items.append(FailedItem(key=cik, error=NO_COMPANYFACTS))
            result.failed_items.extend(
                FailedItem(key=f"{cik}:{key}", error=reason) for key, reason in documents.rejected
            )
            async with engine.connect() as conn:
                result.rows_written += await store_edgar_company(
                    conn, cik, symbol, documents.shares, documents.filings
                )
                await conn.commit()
            logger.debug(
                "edgar_sync.company", cik=cik, shares=len(documents.shares), filings=len(documents.filings)
            )
    return result


async def _active_companies(
    conn: AsyncConnection, ciks: Sequence[str] | None
) -> list[tuple[str, str | None]]:
    result = await conn.execute(
        text(
            "SELECT c.cik, l.symbol FROM companies c "
            "LEFT JOIN listings l ON l.cik = c.cik AND l.is_primary AND l.is_active "
            "WHERE c.is_active AND (CAST(:ciks AS text[]) IS NULL OR c.cik = ANY(CAST(:ciks AS text[]))) "
            "ORDER BY c.cik"
        ),
        {"ciks": list(ciks) if ciks is not None else None},
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
    written += await upsert_events(
        conn,
        [
            EventRow(
                cik=cik,
                symbol=symbol,
                event_date=event.event_date,
                kind=event.kind,
                title=event.title,
                details=event.details,
                source=EVENT_SOURCE,
                source_ref=event.accession,
            )
            for event in filings
        ],
    )
    return written
