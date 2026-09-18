from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator

from stockticker.models.pagination import Page
from stockticker.timeutil import today_ny

MIN_BODY_LEN = 1
MAX_BODY_LEN = 10_000

# System design §5, amended: "Dates run from 1990-01-01 to today (New York) +
# 365." MIN_NOTE_DATE is fixed; the upper bound moves with "today" and is
# computed in the validator below.
MIN_NOTE_DATE = date(1990, 1, 1)
MAX_NOTE_DATE_HORIZON_DAYS = 365


def _trimmed_body(value: str) -> str:
    if "\x00" in value:
        raise ValueError("body must not contain a NUL byte")
    trimmed = value.strip()
    if not (MIN_BODY_LEN <= len(trimmed) <= MAX_BODY_LEN):
        raise ValueError(f"body must be {MIN_BODY_LEN}-{MAX_BODY_LEN} characters after trimming")
    return trimmed


def _max_note_date() -> date:
    return today_ny() + timedelta(days=MAX_NOTE_DATE_HORIZON_DAYS)


def _check_note_date(value: date, field: str) -> None:
    max_date = _max_note_date()
    if not (MIN_NOTE_DATE <= value <= max_date):
        raise ValueError(f"{field} must be between {MIN_NOTE_DATE.isoformat()} and {max_date.isoformat()}")


class Note(BaseModel):
    id: UUID
    cik: str | None
    start_date: date
    end_date: date
    body: str
    created_at: datetime
    updated_at: datetime


class NotesPage(Page[Note]):
    """Keyset page of Notes (system design §5, amended). A distinct
    subclass, not a bare `Page[Note]` alias, so the OpenAPI schema keeps
    the name `NotesPage` instead of a generic-mangled one."""


class NotePut(BaseModel):
    """Body of `PUT /api/v1/notes/{id}` (system design §5, amended: the
    client supplies the id in the path; PUT is an idempotent upsert that
    replaces the old POST/PATCH).

    `end_date` is filled in from `start_date` by a `mode="before"`
    validator -- before pydantic's own type coercion runs -- so the field
    is an honest `date` (not `date | None`) by the time anything reads it;
    no `assert` needed downstream to convince the type checker it's set.
    """

    cik: str | None = None
    start_date: date
    end_date: date
    body: str

    @model_validator(mode="before")
    @classmethod
    def _default_end_date(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("end_date"):
            data = {**data, "end_date": data.get("start_date")}
        return data

    @model_validator(mode="after")
    def _validate(self) -> NotePut:
        self.body = _trimmed_body(self.body)
        _check_note_date(self.start_date, "start_date")
        _check_note_date(self.end_date, "end_date")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self
