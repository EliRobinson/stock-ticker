"""`GET /api/v1/events` queries (system design §5, amended: requires `cik`
or `symbol`, keyset-paginated).

Sort order is `event_date DESC, id DESC` (most recent first, aligned with
Notes' tiebreak). `events (cik, event_date)` is indexed; `id` is the
primary key, so the compound keyset predicate below is still a cheap
index-assisted scan even though `id` isn't itself part of that index.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection


async def fetch_event_rows(
    conn: AsyncConnection,
    *,
    cik: str,
    from_date: date | None,
    to_date: date | None,
    kinds: Sequence[str] | None,
    limit: int,
    cursor_event_date: date | None,
    cursor_id: int | None,
) -> Sequence[Row[Any]]:
    clauses = ["cik = :cik"]
    params: dict[str, Any] = {"cik": cik}

    if from_date is not None:
        clauses.append("event_date >= :from_date")
        params["from_date"] = from_date
    if to_date is not None:
        clauses.append("event_date <= :to_date")
        params["to_date"] = to_date
    if kinds:
        clauses.append("kind = ANY(:kinds)")
        params["kinds"] = list(kinds)
    if cursor_event_date is not None and cursor_id is not None:
        clauses.append("(event_date, id) < (:cursor_event_date, :cursor_id)")
        params["cursor_event_date"] = cursor_event_date
        params["cursor_id"] = cursor_id

    # limit + 1: lets the router tell "there's another page" apart from
    # "that was exactly the last page" without a second round trip.
    sql = text(
        "SELECT id, cik, symbol, event_date, kind, title, details, source, source_ref "
        "FROM events WHERE " + " AND ".join(clauses) + " "
        "ORDER BY event_date DESC, id DESC LIMIT :limit_plus_one"
    )
    result = await conn.execute(sql, {**params, "limit_plus_one": limit + 1})
    return result.all()
