from __future__ import annotations

from fastapi import APIRouter, HTTPException

from stockticker.models.market import MarketResponse
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["market"])


@router.get("/market", response_model=MarketResponse, responses={501: {"model": ProblemDetail}})
async def list_market() -> MarketResponse:
    raise HTTPException(status_code=501, detail="market not implemented yet")
