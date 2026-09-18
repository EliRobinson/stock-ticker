"""`GET /api/v1/events` (system design §5, amended: requires `cik` or
`symbol`, keyset-paginated with `limit`/`cursor`)."""

from __future__ import annotations

from datetime import date
from typing import get_args

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.api.pagination import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    cursor_bigint,
    decode_cursor,
    paginate,
)
from stockticker.api.problems import Problem
from stockticker.api.queries.events import cik_exists, fetch_event_rows, resolve_symbol_to_cik
from stockticker.api.validation import clean_cik, clean_symbol
from stockticker.db import get_app_writer_connection
from stockticker.ingest.symbols import normalize_symbol
from stockticker.models.events import Event, EventKind, EventsPage
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["events"])

_VALID_KINDS = frozenset(get_args(EventKind))


def _parse_kinds(kind: str | None) -> list[str] | None:
    if kind is None:
        return None
    kinds = [item.strip() for item in kind.split(",") if item.strip()]
    invalid = [item for item in kinds if item not in _VALID_KINDS]
    if invalid:
        raise Problem("invalid-event-kind", 422, f"unknown event kind: {', '.join(invalid)}")
    return kinds


@router.get(
    "/events",
    response_model=EventsPage,
    responses={404: {"model": ProblemDetail}, 422: {"model": ProblemDetail}},
)
async def list_events(
    cik: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    kind: str | None = Query(default=None, description="Comma-separated list of event kinds."),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, gt=0, le=MAX_PAGE_LIMIT),
    cursor: str | None = Query(default=None),
    conn: AsyncConnection = Depends(get_app_writer_connection),
) -> EventsPage:
    cik = clean_cik(cik)
    symbol = clean_symbol(symbol)
    if from_ is not None and to is not None and from_ > to:
        raise Problem("invalid-range", 422, "from must not be after to")
    if not cik and not symbol:
        raise Problem("events-requires-cik-or-symbol", 422, "Provide cik or symbol.")

    resolved_cik = cik
    if symbol:
        symbol = normalize_symbol(symbol)
        symbol_cik = await resolve_symbol_to_cik(conn, symbol=symbol)
        if symbol_cik is None:
            raise Problem("unknown-symbol", 404, f"no listing with symbol {symbol}")
        if cik and cik != symbol_cik:
            raise Problem("cik-symbol-mismatch", 422, "cik and symbol refer to different companies")
        resolved_cik = symbol_cik
    elif cik and not await cik_exists(conn, cik=cik):
        raise Problem("unknown-cik", 404, f"no company with cik {cik}")

    assert resolved_cik is not None

    kinds = _parse_kinds(kind)

    cursor_event_date: date | None = None
    cursor_id: int | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        try:
            cursor_event_date = date.fromisoformat(str(decoded["event_date"]))
        except (KeyError, ValueError) as exc:
            raise Problem("invalid-cursor", 422, "cursor is not a valid page token") from exc
        cursor_id = cursor_bigint(decoded, "id")

    rows = await fetch_event_rows(
        conn,
        cik=resolved_cik,
        from_date=from_,
        to_date=to,
        kinds=kinds,
        limit=limit,
        cursor_event_date=cursor_event_date,
        cursor_id=cursor_id,
    )

    items = [Event.model_validate(row._mapping) for row in rows]
    page_items, next_cursor = paginate(
        items,
        limit=limit,
        cursor_of=lambda item: {"event_date": item.event_date.isoformat(), "id": item.id},
    )
    return EventsPage(items=page_items, next_cursor=next_cursor)
