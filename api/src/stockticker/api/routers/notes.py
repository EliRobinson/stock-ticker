from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from stockticker.models.notes import Note, NoteCreate, NoteUpdate
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["notes"])


@router.get("/notes", response_model=list[Note], responses={501: {"model": ProblemDetail}})
async def list_notes(
    cik: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    market_only: bool = Query(default=False),
) -> list[Note]:
    raise HTTPException(status_code=501, detail="notes not implemented yet")


@router.post(
    "/notes",
    response_model=Note,
    status_code=201,
    responses={422: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def create_note(payload: NoteCreate) -> Note:
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
