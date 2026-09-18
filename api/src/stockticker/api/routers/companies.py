"""`GET /api/v1/companies/{cik}` (system design §5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.api.problems import Problem
from stockticker.api.queries.companies import (
    fetch_company_row,
    fetch_first_bar_date,
    fetch_listing_rows,
    fetch_market_cap_row,
    fetch_week_52_range,
)
from stockticker.api.validation import clean_cik
from stockticker.db import get_app_writer_connection
from stockticker.models.companies import CompanyDetail, ListingSummary, MarketCapSummary
from stockticker.models.problem import ProblemDetail
from stockticker.timeutil import today_ny

router = APIRouter(tags=["companies"])


@router.get(
    "/companies/{cik}",
    response_model=CompanyDetail,
    responses={404: {"model": ProblemDetail}, 422: {"model": ProblemDetail}},
)
async def get_company(cik: str, conn: AsyncConnection = Depends(get_app_writer_connection)) -> CompanyDetail:
    clean_cik(cik)
    company = await fetch_company_row(conn, cik=cik)
    if company is None:
        raise Problem("unknown-cik", 404, f"no company with cik {cik}")

    today = today_ny()
    listing_rows = await fetch_listing_rows(conn, cik=cik)
    market_cap_row = await fetch_market_cap_row(conn, cik=cik, today=today)
    range_row = await fetch_week_52_range(conn, cik=cik, today=today)
    first_bar_date = await fetch_first_bar_date(conn, cik=cik)

    return CompanyDetail.model_validate(
        {
            **dict(company._mapping),
            "listings": [ListingSummary.model_validate(row._mapping) for row in listing_rows],
            "market_cap": (
                MarketCapSummary.model_validate(
                    {**dict(market_cap_row._mapping), "is_approx": market_cap_row.is_multi_class}
                )
                if market_cap_row is not None
                else None
            ),
            "week_52_high": range_row.high if range_row is not None else None,
            "week_52_low": range_row.low if range_row is not None else None,
            "first_bar_date": first_bar_date,
        }
    )
