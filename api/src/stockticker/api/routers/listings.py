"""`GET /api/v1/listings/{symbol}/bars` (system design §5, amended: takes
`timeframe`, echoed back; any value other than `1d` is a 422)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.api.problems import Problem
from stockticker.api.queries.bars import fetch_bar_rows, listing_exists
from stockticker.db import get_app_writer_connection
from stockticker.ingest.symbols import normalize_symbol
from stockticker.models.bars import Bar, BarsResponse, Timeframe
from stockticker.models.problem import ProblemDetail
from stockticker.timeutil import today_ny

router = APIRouter(tags=["listings"])

DEFAULT_FROM_DATE = date(2018, 1, 1)


@router.get(
    "/listings/{symbol}/bars",
    response_model=BarsResponse,
    responses={404: {"model": ProblemDetail}, 422: {"model": ProblemDetail}},
)
async def list_bars(
    symbol: str,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    timeframe: Timeframe = Query(default="1d"),
    conn: AsyncConnection = Depends(get_app_writer_connection),
) -> BarsResponse:
    symbol = normalize_symbol(symbol)
    from_date = from_ or DEFAULT_FROM_DATE
    to_date = to or today_ny()
    if from_date > to_date:
        raise Problem("invalid-range", 422, "from must not be after to")

    if not await listing_exists(conn, symbol=symbol):
        raise Problem("unknown-symbol", 404, f"no listing with symbol {symbol}")

    rows = await fetch_bar_rows(conn, symbol=symbol, from_date=from_date, to_date=to_date)

    return BarsResponse(
        timeframe=timeframe,
        bars=[Bar.model_validate(row._mapping) for row in rows],
    )
