from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from stockticker.models.events import Event
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["events"])


@router.get("/events", response_model=list[Event], responses={501: {"model": ProblemDetail}})
async def list_events(
    cik: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    kind: str | None = Query(default=None, description="Comma-separated list of event kinds."),
) -> list[Event]:
    raise HTTPException(status_code=501, detail="events not implemented yet")
