"""`constituents_sync` (system design §4): upsert Companies and Listings from
the Wikipedia Constituent List.

- A new Listing starts with `backfill_completed_at` null; `bars_backfill`
  sets it.
- Each Company gets exactly one primary Listing: `share_class_rules.price_symbol`
  when a rule exists and that symbol is listed, otherwise its first row in
  the table.
- A Company or Listing missing from the table is deactivated only after it
  has been missing on `MISSING_SYNCS_BEFORE_DEACTIVATION` consecutive syncs.
  The per-key miss counts live in `ingest_watermarks` under this job.
- More than `MAX_COMPANY_DEACTIVATIONS_PER_RUN` Company deactivations in one
  run means the parse broke, not that the index changed. The run fails and
  the whole transaction rolls back, so the last good list stays.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.config import get_settings
from stockticker.ingest.http import build_http_client, request
from stockticker.ingest.job import JobResult
from stockticker.ingest.wikipedia.parser import ConstituentRow, parse_constituents
from stockticker.logging import get_logger

logger = get_logger(__name__)

JOB_NAME = "constituents_sync"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
EVENT_SOURCE = "wikipedia"
MISSING_SYNCS_BEFORE_DEACTIVATION = 2
MAX_COMPANY_DEACTIVATIONS_PER_RUN = 10

_MISSING_COMPANY = "missing_company:"
_MISSING_LISTING = "missing_listing:"


class TooManyDeactivationsError(Exception):
    def __init__(self, ciks: Sequence[str]) -> None:
        self.ciks = list(ciks)
        super().__init__(
            f"{len(ciks)} Companies would be deactivated in one run "
            f"(limit {MAX_COMPANY_DEACTIVATIONS_PER_RUN}); keeping the last good list"
        )


@dataclass(slots=True)
class ConstituentsSyncSummary:
    companies_upserted: int = 0
    listings_upserted: int = 0
    events_written: int = 0
    companies_deactivated: int = 0
    listings_deactivated: int = 0

    @property
    def rows_written(self) -> int:
        return (
            self.companies_upserted
            + self.listings_upserted
            + self.events_written
            + self.companies_deactivated
            + self.listings_deactivated
        )


def user_agent(contact: str | None) -> str:
    base = "stock-ticker/0.1 (local research tool)"
    return f"{base} {contact}" if contact else base


async def fetch_constituents_html(client: httpx.AsyncClient) -> str:
    response = await request(client, "GET", WIKIPEDIA_URL)
    return response.text


async def run_constituents_sync(engine: AsyncEngine, *, contact: str | None) -> JobResult:
    async with build_http_client(headers={"User-Agent": user_agent(contact)}) as client:
        html = await fetch_constituents_html(client)
    rows = parse_constituents(html)
    async with engine.connect() as conn:
        summary = await apply_constituents(conn, rows)
        await conn.commit()
    logger.info("constituents_sync.applied", rows=len(rows), **_as_log(summary))
    return JobResult(rows_written=summary.rows_written)


async def apply_constituents(
    conn: AsyncConnection, rows: Sequence[ConstituentRow]
) -> ConstituentsSyncSummary:
    """Apply one parsed Constituent List inside the caller's transaction.
    Does not commit."""
    _reject_duplicate_symbols(rows)
    summary = ConstituentsSyncSummary()
    by_cik = _group_by_cik(rows)
    rules = await _price_symbols_by_cik(conn)
    primaries = {cik: _primary_symbol(cik_rows, rules.get(cik)) for cik, cik_rows in by_cik.items()}

    summary.companies_upserted = await _upsert_companies(conn, by_cik, primaries)
    summary.listings_upserted = await _upsert_listings(conn, rows, primaries)
    summary.events_written = await _write_index_added_events(conn, rows, primaries)

    listed_ciks = list(by_cik)
    listed_symbols = [row.symbol for row in rows]
    missing_companies = await _bump_missing(conn, "companies", "cik", _MISSING_COMPANY, listed_ciks)
    missing_listings = await _bump_missing(conn, "listings", "symbol", _MISSING_LISTING, listed_symbols)
    await _clear_counters_except(
        conn, [_MISSING_COMPANY + key for key in missing_companies], _MISSING_COMPANY
    )
    await _clear_counters_except(conn, [_MISSING_LISTING + key for key in missing_listings], _MISSING_LISTING)

    companies_to_drop = [
        cik for cik, misses in missing_companies.items() if misses >= MISSING_SYNCS_BEFORE_DEACTIVATION
    ]
    if len(companies_to_drop) > MAX_COMPANY_DEACTIVATIONS_PER_RUN:
        raise TooManyDeactivationsError(companies_to_drop)
    listings_to_drop = [
        symbol for symbol, misses in missing_listings.items() if misses >= MISSING_SYNCS_BEFORE_DEACTIVATION
    ]
    summary.companies_deactivated = await _deactivate(conn, "companies", "cik", companies_to_drop)
    summary.listings_deactivated = await _deactivate(conn, "listings", "symbol", listings_to_drop)
    return summary


def _reject_duplicate_symbols(rows: Sequence[ConstituentRow]) -> None:
    seen: set[str] = set()
    for row in rows:
        if row.symbol in seen:
            raise ValueError(f"symbol {row.symbol} appears twice in the Constituent List")
        seen.add(row.symbol)


def _group_by_cik(rows: Sequence[ConstituentRow]) -> dict[str, list[ConstituentRow]]:
    grouped: dict[str, list[ConstituentRow]] = {}
    for row in rows:
        grouped.setdefault(row.cik, []).append(row)
    return grouped


def _primary_symbol(cik_rows: Sequence[ConstituentRow], rule_symbol: str | None) -> str:
    symbols = [row.symbol for row in cik_rows]
    if rule_symbol is not None and rule_symbol in symbols:
        return rule_symbol
    return symbols[0]


async def _price_symbols_by_cik(conn: AsyncConnection) -> dict[str, str]:
    result = await conn.execute(text("SELECT cik, price_symbol FROM share_class_rules"))
    return {row.cik: row.price_symbol for row in result}


async def _upsert_companies(
    conn: AsyncConnection, by_cik: dict[str, list[ConstituentRow]], primaries: dict[str, str]
) -> int:
    params = []
    for cik, cik_rows in by_cik.items():
        primary = next(row for row in cik_rows if row.symbol == primaries[cik])
        dates = [row.date_added for row in cik_rows if row.date_added is not None]
        params.append(
            {
                "cik": cik,
                "name": primary.name,
                "sector": primary.sector,
                "sub_industry": primary.sub_industry,
                "headquarters": primary.headquarters,
                "date_added": min(dates) if dates else None,
            }
        )
    await conn.execute(
        text(
            "INSERT INTO companies (cik, name, sector, sub_industry, headquarters, date_added, is_active) "
            "VALUES (:cik, :name, :sector, :sub_industry, :headquarters, :date_added, true) "
            "ON CONFLICT (cik) DO UPDATE SET name = excluded.name, sector = excluded.sector, "
            "sub_industry = excluded.sub_industry, headquarters = excluded.headquarters, "
            "date_added = excluded.date_added, is_active = true, updated_at = now()"
        ),
        params,
    )
    return len(params)


async def _upsert_listings(
    conn: AsyncConnection, rows: Sequence[ConstituentRow], primaries: dict[str, str]
) -> int:
    # Demote every other primary first: the partial unique index
    # (cik) WHERE is_primary AND is_active is checked row by row.
    await conn.execute(
        text(
            "UPDATE listings SET is_primary = false, updated_at = now() "
            "WHERE is_primary AND cik = ANY(:ciks) AND NOT (symbol = ANY(:primaries))"
        ),
        {"ciks": list(primaries), "primaries": list(primaries.values())},
    )
    await conn.execute(
        text(
            "INSERT INTO listings (symbol, cik, is_primary, is_active) "
            "VALUES (:symbol, :cik, :is_primary, true) "
            "ON CONFLICT (symbol) DO UPDATE SET cik = excluded.cik, is_primary = excluded.is_primary, "
            "is_active = true, updated_at = now()"
        ),
        [
            {"symbol": row.symbol, "cik": row.cik, "is_primary": primaries[row.cik] == row.symbol}
            for row in sorted(rows, key=lambda row: primaries[row.cik] == row.symbol)
        ],
    )
    return len(rows)


async def _write_index_added_events(
    conn: AsyncConnection, rows: Sequence[ConstituentRow], primaries: dict[str, str]
) -> int:
    # Primary rows first, so a shared (cik, date) event names the primary symbol.
    dated = [row for row in sorted(rows, key=lambda row: primaries[row.cik] != row.symbol) if row.date_added]
    if not dated:
        return 0
    result = await conn.execute(
        text(
            "INSERT INTO events (cik, symbol, event_date, kind, title, details, source, source_ref) "
            "SELECT e.cik, e.symbol, e.event_date, 'index_added', e.title, e.details, :source, "
            "e.cik || ':' || e.event_date::text "
            "FROM unnest(CAST(:cik AS text[]), CAST(:symbol AS text[]), CAST(:event_date AS date[]), "
            "CAST(:title AS text[]), CAST(:details AS jsonb[])) WITH ORDINALITY "
            "AS e(cik, symbol, event_date, title, details, position) "
            "ORDER BY e.position "
            "ON CONFLICT (source, source_ref) DO NOTHING"
        ),
        {
            "source": EVENT_SOURCE,
            "cik": [row.cik for row in dated],
            "symbol": [row.symbol for row in dated],
            "event_date": [row.date_added for row in dated],
            "title": [f"Added to the S&P 500 ({row.symbol})" for row in dated],
            "details": [json.dumps({"symbol": row.symbol}) for row in dated],
        },
    )
    return result.rowcount or 0


async def _bump_missing(
    conn: AsyncConnection, table: str, key_column: str, prefix: str, present: Sequence[str]
) -> dict[str, int]:
    """Increment the miss counter of every active row not in `present`, and
    return {key: consecutive misses}."""
    result = await conn.execute(
        text(
            "INSERT INTO ingest_watermarks (job, key, value, updated_at) "
            f"SELECT :job, :prefix || t.{key_column}, '1', now() FROM {table} t "
            f"WHERE t.is_active AND NOT (t.{key_column} = ANY(:present)) "
            "ON CONFLICT (job, key) DO UPDATE SET "
            "value = (ingest_watermarks.value::int + 1)::text, updated_at = now() "
            "RETURNING key, value"
        ),
        {"job": JOB_NAME, "prefix": prefix, "present": list(present)},
    )
    return {row.key.removeprefix(prefix): int(row.value) for row in result}


async def _clear_counters_except(conn: AsyncConnection, keep: Sequence[str], prefix: str) -> None:
    await conn.execute(
        text(
            "DELETE FROM ingest_watermarks WHERE job = :job AND starts_with(key, :prefix) "
            "AND NOT (key = ANY(:keep))"
        ),
        {"job": JOB_NAME, "prefix": prefix, "keep": list(keep)},
    )


async def _deactivate(conn: AsyncConnection, table: str, key_column: str, keys: Sequence[str]) -> int:
    if not keys:
        return 0
    result = await conn.execute(
        text(
            f"UPDATE {table} SET is_active = false, updated_at = now() "
            f"WHERE is_active AND {key_column} = ANY(:keys)"
        ),
        {"keys": list(keys)},
    )
    if result.rowcount:
        logger.info("constituents_sync.deactivated", table=table, keys=list(keys))
    return result.rowcount or 0


async def constituents_sync(conn: AsyncConnection) -> JobResult:
    """Job handler. `conn` holds the wrapper's advisory lock; the work runs
    on connections of its own."""
    return await run_constituents_sync(conn.engine, contact=get_settings().sec_user_agent)


def _as_log(summary: ConstituentsSyncSummary) -> dict[str, int]:
    return {
        "companies_upserted": summary.companies_upserted,
        "listings_upserted": summary.listings_upserted,
        "events_written": summary.events_written,
        "companies_deactivated": summary.companies_deactivated,
        "listings_deactivated": summary.listings_deactivated,
    }
