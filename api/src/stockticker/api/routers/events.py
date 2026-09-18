from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from stockticker.api.problems import Problem
from stockticker.models.events import EventsPage
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["events"])


@router.get(
    "/events",
    response_model=EventsPage,
    responses={422: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def list_events(
    cik: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    kind: str | None = Query(default=None, description="Comma-separated list of event kinds."),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
) -> EventsPage:
    if cik is None and symbol is None:
        raise Problem("events-requires-cik-or-symbol", 422, "Provide cik or symbol.")
    raise HTTPException(status_code=501, detail="events not implemented yet")
