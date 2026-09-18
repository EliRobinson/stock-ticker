"""`Page[T]`: the generic keyset-page response shape shared by `EventsPage`
and `NotesPage` (system design §5, amended). Kept separate from
`stockticker.api.pagination` (which owns cursor encode/decode and raises
`Problem`) so that `stockticker.models` -- imported by `stockticker.api.problems`
itself, via `models.problem.ProblemDetail` -- never has to import anything
back out of `stockticker.api`, which would be a circular import.
"""

from __future__ import annotations

from pydantic import BaseModel


class Page[T: BaseModel](BaseModel):
    items: list[T]
    next_cursor: str | None = None
