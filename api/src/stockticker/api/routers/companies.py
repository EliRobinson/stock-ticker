from __future__ import annotations

from fastapi import APIRouter, HTTPException

from stockticker.models.companies import CompanyDetail
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["companies"])


@router.get(
    "/companies/{cik}",
    response_model=CompanyDetail,
    responses={404: {"model": ProblemDetail}, 501: {"model": ProblemDetail}},
)
async def get_company(cik: str) -> CompanyDetail:
    raise HTTPException(status_code=501, detail="companies not implemented yet")
