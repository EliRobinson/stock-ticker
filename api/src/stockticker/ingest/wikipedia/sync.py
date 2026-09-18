"""`constituents_sync` (system design §4): upsert Companies and Listings from
the Wikipedia Constituent List.

- A new Listing starts with `backfill_completed_at` null; `bars_backfill`
  sets it.
- Each Company gets exactly one primary Listing: `share_class_rules.price_symbol`
  when a rule exists and that symbol is listed, otherwise its first row in
  the table.
- A Company or Listing is deactivated only once it has been missing on two
  consecutive New York days: it is active, absent from today's list, and
  absent from the last list parsed on an earlier day. Several runs on one
  day count once. The last lists live in `ingest_watermarks` under this job.
- More than `MAX_DEACTIVATIONS_PER_RUN` Company or Listing deactivations in
  one run means the parse broke, not that the index changed. The run fails
  and the whole transaction rolls back, so the last good list stays.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.http import RateBudgetName, build_http_client, request
from stockticker.ingest.job import JobContext, JobResult
from stockticker.ingest.sinks import EventRow, upsert_events
from stockticker.ingest.watermarks import read_watermark, write_watermark
from stockticker.ingest.wikipedia.parser import ConstituentRow, parse_constituents
from stockticker.logging import get_logger
from stockticker.timeutil import today_ny

logger = get_logger(__name__)

JOB_NAME = "constituents_sync"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Operator-neutral on purpose: the SEC contact in SEC_USER_AGENT is for SEC only.
USER_AGENT = "stock-ticker/0.1 (local research tool)"
EVENT_SOURCE = "wikipedia"
MAX_DEACTIVATIONS_PER_RUN = 10
LISTS_KEY = "lists"


class TooManyDeactivationsError(Exception):
    def __init__(self, table: str, keys: Sequence[str]) -> None:
        self.table = table
        self.keys = sorted(keys)
        super().__init__(
            f"{len(keys)} {table} would be deactivated in one run "
            f"(limit {MAX_DEACTIVATIONS_PER_RUN}); keeping the last good list"
        )


@dataclass(frozen=True, slots=True)
class ParsedList:
    day: date
    symbols: frozenset[str]
    ciks: frozenset[str]

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "symbols": sorted(self.symbols), "ciks": sorted(self.ciks)}

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> ParsedList | None:
        if not data:
            return None
        return cls(
            day=date.fromisoformat(data["day"]),
            symbols=frozenset(data["symbols"]),
            ciks=frozenset(data["ciks"]),
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


async def fetch_constituents_html(client: httpx.AsyncClient) -> str:
    response = await request(client, "GET", WIKIPEDIA_URL, rate_budget=RateBudgetName.WIKIPEDIA)
    return response.text


async def constituents_sync(ctx: JobContext) -> JobResult:
    return await run_constituents_sync(ctx.engine)


async def run_constituents_sync(engine: AsyncEngine) -> JobResult:
    async with build_http_client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        html = await fetch_constituents_html(client)
    parsed = parse_constituents(html)
    async with engine.connect() as conn:
        summary = await apply_constituents(conn, parsed.rows)
        await conn.commit()
    logger.info(
        "constituents_sync.applied",
        rows=len(parsed.rows),
        rejected=len(parsed.rejected),
        **_as_log(summary),
    )
    return JobResult(rows_written=summary.rows_written, failed_items=list(parsed.rejected))


async def apply_constituents(
    conn: AsyncConnection, rows: Sequence[ConstituentRow], *, today: date | None = None
) -> ConstituentsSyncSummary:
    """Apply one parsed Constituent List inside the caller's transaction.
    Does not commit."""
    _reject_duplicate_symbols(rows)
    today = today or today_ny()
    summary = ConstituentsSyncSummary()
    by_cik = _group_by_cik(rows)
    rules = await _price_symbols_by_cik(conn)
    primaries = {cik: _primary_symbol(cik_rows, rules.get(cik)) for cik, cik_rows in by_cik.items()}

    summary.companies_upserted = await _upsert_companies(conn, by_cik, primaries)
    summary.listings_upserted = await _upsert_listings(conn, rows, primaries)
    summary.events_written = await _write_index_added_events(conn, rows, primaries)

    current = ParsedList(day=today, symbols=frozenset(row.symbol for row in rows), ciks=frozenset(by_cik))
    stored = json.loads(await read_watermark(conn, JOB_NAME, LISTS_KEY) or "{}")
    latest = ParsedList.from_json(stored.get("latest"))
    prior = ParsedList.from_json(stored.get("prior"))
    if latest is not None and latest.day < today:
        prior = latest
    await write_watermark(
        conn,
        JOB_NAME,
        LISTS_KEY,
        json.dumps({"latest": current.to_json(), "prior": prior.to_json() if prior else None}),
    )
    if prior is None:
        return summary

    companies_to_drop = await _missing_twice(conn, "companies", "cik", current.ciks | prior.ciks)
    listings_to_drop = await _missing_twice(conn, "listings", "symbol", current.symbols | prior.symbols)
    for table, keys in (("Companies", companies_to_drop), ("Listings", listings_to_drop)):
        if len(keys) > MAX_DEACTIVATIONS_PER_RUN:
            raise TooManyDeactivationsError(table, keys)
    summary.companies_deactivated = await _deactivate(conn, "companies", "cik", companies_to_drop)
    summary.listings_deactivated = await _deactivate(conn, "listings", "symbol", listings_to_drop)
    return summary


async def _missing_twice(
    conn: AsyncConnection, table: str, key_column: str, seen_recently: frozenset[str]
) -> list[str]:
    result = await conn.execute(
        text(f"SELECT {key_column} AS key FROM {table} WHERE is_active AND NOT ({key_column} = ANY(:seen))"),
        {"seen": sorted(seen_recently)},
    )
    return [row.key for row in result]


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
    # Primary rows last: upsert_events keeps the last of a duplicate
    # (cik, date), so a shared event names the primary symbol.
    ordered = sorted(rows, key=lambda row: primaries[row.cik] == row.symbol)
    result = await upsert_events(
        conn,
        [
            EventRow(
                cik=row.cik,
                symbol=row.symbol,
                event_date=row.date_added,
                kind="index_added",
                title=f"Added to the S&P 500 ({row.symbol})",
                details={"symbol": row.symbol},
                source=EVENT_SOURCE,
                source_ref=f"{row.cik}:{row.date_added.isoformat()}",
            )
            for row in ordered
            if row.date_added is not None
        ],
    )
    # Every Company was upserted just above, so no Event can have an unknown CIK.
    return result.rows_written


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


def _as_log(summary: ConstituentsSyncSummary) -> dict[str, int]:
    return {
        "companies_upserted": summary.companies_upserted,
        "listings_upserted": summary.listings_upserted,
        "events_written": summary.events_written,
        "companies_deactivated": summary.companies_deactivated,
        "listings_deactivated": summary.listings_deactivated,
    }
