"""`/api/v1/notes` (system design §5, amended: `PUT /notes/{id}` is an
idempotent upsert with a client-supplied UUID, replacing the old POST and
PATCH; `GET /notes` is keyset-paginated)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.api.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, decode_cursor, paginate
from stockticker.api.problems import Problem
from stockticker.api.queries.notes import cik_exists, delete_note, fetch_note_rows, upsert_note
from stockticker.api.validation import clean_cik
from stockticker.db import get_app_writer_connection
from stockticker.models.notes import Note, NotePut, NotesPage
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["notes"])


def _cursor_from_note(note: Note) -> dict[str, object]:
    return {"start_date": note.start_date.isoformat(), "id": str(note.id)}


@router.get("/notes", response_model=NotesPage, responses={422: {"model": ProblemDetail}})
async def list_notes(
    cik: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    market_only: bool = Query(default=False),
    include_market: bool = Query(
        default=False, description="With cik, also return whole-market Notes (cik is null)."
    ),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, gt=0, le=MAX_PAGE_LIMIT),
    cursor: str | None = Query(default=None),
    conn: AsyncConnection = Depends(get_app_writer_connection),
) -> NotesPage:
    cik = clean_cik(cik)
    if from_ is not None and to is not None and from_ > to:
        raise Problem("invalid-range", 422, "from must not be after to")
    if cik and market_only:
        raise Problem("conflicting-filters", 422, "cik and market_only cannot both be set")

    cursor_start_date: date | None = None
    cursor_id: UUID | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        try:
            cursor_start_date = date.fromisoformat(str(decoded["start_date"]))
            cursor_id = UUID(str(decoded["id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise Problem("invalid-cursor", 422, "cursor is not a valid page token") from exc

    rows = await fetch_note_rows(
        conn,
        cik=cik,
        market_only=market_only,
        include_market=include_market,
        from_date=from_,
        to_date=to,
        limit=limit,
        cursor_start_date=cursor_start_date,
        cursor_id=cursor_id,
    )
    items = [Note.model_validate(row._mapping) for row in rows]
    page_items, next_cursor = paginate(items, limit=limit, cursor_of=_cursor_from_note)
    return NotesPage(items=page_items, next_cursor=next_cursor)


@router.put(
    "/notes/{note_id}",
    response_model=Note,
    responses={422: {"model": ProblemDetail}},
)
async def put_note(
    note_id: UUID,
    payload: NotePut,
    response: Response,
    conn: AsyncConnection = Depends(get_app_writer_connection),
) -> Note:
    payload.cik = clean_cik(payload.cik)
    if payload.cik is not None and not await cik_exists(conn, cik=payload.cik):
        raise Problem("unknown-cik", 422, f"no company with cik {payload.cik}")

    row, created = await upsert_note(
        conn,
        note_id=note_id,
        cik=payload.cik,
        start_date=payload.start_date,
        end_date=payload.end_date,
        body=payload.body,
    )
    response.status_code = 201 if created else 200
    return Note.model_validate(row._mapping)


@router.delete("/notes/{note_id}", status_code=204)
async def remove_note(note_id: UUID, conn: AsyncConnection = Depends(get_app_writer_connection)) -> None:
    await delete_note(conn, note_id=note_id)
