"""`GET /api/v1/market` (system design §5, amended: also carries
`server_time`/`market_clock` so the client never needs a second call to
`/api/v1/status` just to know whether the market is open).

Gzipped when the client says it accepts it (system design §5: "Use gzip"),
unlike every other route in this package -- `/api/v1/chat`'s SSE stream
explicitly turns gzip *off* (§6), so this is done locally with a plain
`Response` rather than a global `GZipMiddleware` that would also wrap the
chat route.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.responses import Response

from stockticker.api.queries.market import fetch_market_rows
from stockticker.db import get_app_writer_connection
from stockticker.marketdata import fetch_market_clock
from stockticker.models.market import MarketResponse, MarketRow
from stockticker.timeutil import today_ny

router = APIRouter(tags=["market"])


@router.get("/market", response_model=MarketResponse)
async def list_market(
    request: Request, conn: AsyncConnection = Depends(get_app_writer_connection)
) -> Response:
    rows = await fetch_market_rows(conn, today=today_ny())
    payload = MarketResponse(
        server_time=datetime.now(UTC),
        market_clock=await fetch_market_clock(),
        listings=[MarketRow.model_validate(row._mapping) for row in rows],
    )
    body = payload.model_dump_json().encode()
    accept_encoding = request.headers.get("accept-encoding", "")
    if "gzip" in accept_encoding:
        return Response(
            content=gzip.compress(body),
            media_type="application/json",
            headers={"Content-Encoding": "gzip"},
        )
    return Response(content=body, media_type="application/json")
