from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from stockticker.models.bars import BarsResponse, Timeframe
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["listings"])


@router.get(
    "/listings/{symbol}/bars",
    response_model=BarsResponse,
    responses={404: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def list_bars(
    symbol: str,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    timeframe: Timeframe = Query(default="1d"),
) -> BarsResponse:
    raise HTTPException(status_code=501, detail="bars not implemented yet")
