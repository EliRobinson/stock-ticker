from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from stockticker.models.notes import Note, NotePut, NotesPage, NoteUpdate
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["notes"])


@router.get("/notes", response_model=NotesPage, responses={501: {"model": ProblemDetail}})
async def list_notes(
    cik: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    market_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
) -> NotesPage:
    raise HTTPException(status_code=501, detail="notes not implemented yet")


@router.put(
    "/notes/{note_id}",
    response_model=Note,
    responses={422: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def put_note(note_id: UUID, payload: NotePut) -> Note:
    """Idempotent upsert (system design §5): a first PUT creates, a repeat
    PUT with the same `note_id` replaces it."""
    raise HTTPException(status_code=501, detail="notes not implemented yet")


@router.patch(
    "/notes/{note_id}",
    response_model=Note,
    responses={404: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def update_note(note_id: UUID, payload: NoteUpdate) -> Note:
    raise HTTPException(status_code=501, detail="notes not implemented yet")


@router.delete(
    "/notes/{note_id}",
    status_code=204,
    responses={404: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def delete_note(note_id: UUID) -> None:
    raise HTTPException(status_code=501, detail="notes not implemented yet")
