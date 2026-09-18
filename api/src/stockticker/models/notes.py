from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

MIN_BODY_LEN = 1
MAX_BODY_LEN = 10_000


def _trimmed_body(value: str) -> str:
    trimmed = value.strip()
    if not (MIN_BODY_LEN <= len(trimmed) <= MAX_BODY_LEN):
        raise ValueError(f"body must be {MIN_BODY_LEN}-{MAX_BODY_LEN} characters after trimming")
    return trimmed


class Note(BaseModel):
    id: UUID
    cik: str | None
    start_date: date
    end_date: date
    body: str
    created_at: datetime
    updated_at: datetime


class NotePut(BaseModel):
    """Body for `PUT /api/v1/notes/{id}` -- an idempotent upsert. The
    client generates `id` (a UUID) and puts it in the URL, not here: a
    first PUT creates, a repeat PUT with the same id replaces it. That's
    what makes the UI's Undo a plain retry (re-PUT the same id) rather
    than a new resource."""

    cik: str | None = None
    start_date: date
    end_date: date | None = None
    body: str

    @field_validator("body")
    @classmethod
    def _validate_body(cls, value: str) -> str:
        return _trimmed_body(value)


class NotesPage(BaseModel):
    items: list[Note]
    next_cursor: str | None = None


class NoteUpdate(BaseModel):
    """Partial update. A field omitted from the request body is left
    unchanged; the router applies this with `model_dump(exclude_unset=True)`,
    so an explicit `null` for `cik` clears it (market-wide note)."""

    cik: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    body: str | None = None

    @field_validator("body")
    @classmethod
    def _validate_body(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed_body(value)
