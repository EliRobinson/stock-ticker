"""RFC 9457 `application/problem+json` body.

Every error response in the API (including FastAPI's own 404/405/422) uses
this shape — see `stockticker.api.problems`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[dict[str, object]] | None = Field(
        default=None, description="Per-field validation errors, present on 422 responses."
    )
