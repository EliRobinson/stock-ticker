"""`/api/v1/notes` queries (system design §5, amended).

**Overlap filter.** A Note `[start_date, end_date]` matches a requested
`[from, to]` window when the two ranges overlap: `note.start_date <= to AND
note.end_date >= from`, with a missing bound treated as unbounded on that
side. **Order.** `start_date DESC, id DESC` -- aligned with Events' tiebreak
direction. **`include_market`** (with `cik`) unions in whole-market Notes
(`cik IS NULL`) alongside the company's own; `market_only` is the opposite
extreme, cik-less Notes only, and conflicts with `cik` (system design
review: "cik together with market_only returns 422 conflicting-filters").

**Upsert.** `PUT /notes/{id}` is one `INSERT ... ON CONFLICT (id) DO UPDATE
... RETURNING ..., (xmax = 0) AS created` -- a single atomic statement, not
a check-then-branch (which has a race between two concurrent PUTs of the
same id, and always issues a write even when nothing changed). The `DO
UPDATE`'s `WHERE ... IS DISTINCT FROM` guard means an identical PUT is a
no-op at the row level: the `BEFORE UPDATE` trigger that stamps
`updated_at` never fires unless a column's value actually changed. Because
Postgres returns *no row* from `RETURNING` when that `WHERE` excludes the
conflicting row (a true no-op replace), the router falls back to a plain
`SELECT` in that one case to still return the (unchanged) Note.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

_NOTE_FIELDS = "id, cik, start_date, end_date, body, created_at, updated_at"


async def fetch_note_rows(
    conn: AsyncConnection,
    *,
    cik: str | None,
    market_only: bool,
    include_market: bool,
    from_date: date | None,
    to_date: date | None,
    limit: int,
    cursor_start_date: date | None,
    cursor_id: UUID | None,
) -> Sequence[Row[Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if market_only:
        clauses.append("cik IS NULL")
    elif cik:
        clauses.append("(cik = :cik OR cik IS NULL)" if include_market else "cik = :cik")
        params["cik"] = cik

    if to_date is not None:
        clauses.append("start_date <= :to_date")
        params["to_date"] = to_date
    if from_date is not None:
        clauses.append("end_date >= :from_date")
        params["from_date"] = from_date
    if cursor_start_date is not None and cursor_id is not None:
        clauses.append(
            "(start_date < :cursor_start_date OR (start_date = :cursor_start_date AND id < :cursor_id))"
        )
        params["cursor_start_date"] = cursor_start_date
        params["cursor_id"] = cursor_id

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # limit + 1: lets the router tell "there's another page" apart from
    # "that was exactly the last page" without a second round trip.
    sql = text(
        f"SELECT {_NOTE_FIELDS} FROM notes {where} ORDER BY start_date DESC, id DESC LIMIT :limit_plus_one"
    )
    result = await conn.execute(sql, {**params, "limit_plus_one": limit + 1})
    return result.all()


async def upsert_note(
    conn: AsyncConnection,
    *,
    note_id: UUID,
    cik: str | None,
    start_date: date,
    end_date: date,
    body: str,
) -> tuple[Row[Any], bool]:
    """Returns `(row, created)`. `created` is true for a first PUT, false
    for a replace (whether or not the replace actually changed anything)."""
    row = (
        await conn.execute(
            text(
                "INSERT INTO notes (id, cik, start_date, end_date, body) "
                "VALUES (:id, :cik, :start_date, :end_date, :body) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  cik = EXCLUDED.cik, start_date = EXCLUDED.start_date, "
                "  end_date = EXCLUDED.end_date, body = EXCLUDED.body "
                "WHERE notes.cik IS DISTINCT FROM EXCLUDED.cik "
                "   OR notes.start_date IS DISTINCT FROM EXCLUDED.start_date "
                "   OR notes.end_date IS DISTINCT FROM EXCLUDED.end_date "
                "   OR notes.body IS DISTINCT FROM EXCLUDED.body "
                f"RETURNING {_NOTE_FIELDS}, (xmax = 0) AS created"
            ),
            {"id": note_id, "cik": cik, "start_date": start_date, "end_date": end_date, "body": body},
        )
    ).first()
    await conn.commit()
    if row is not None:
        return row, bool(row.created)

    # The WHERE clause excluded an identical replace -- no row came back
    # from RETURNING even though the note exists. Fetch it as-is; this is
    # always a (no-op) replace, never a create.
    existing = (
        await conn.execute(text(f"SELECT {_NOTE_FIELDS} FROM notes WHERE id = :id"), {"id": note_id})
    ).first()
    assert existing is not None
    return existing, False


async def delete_note(conn: AsyncConnection, *, note_id: UUID) -> None:
    await conn.execute(text("DELETE FROM notes WHERE id = :id"), {"id": note_id})
    await conn.commit()
