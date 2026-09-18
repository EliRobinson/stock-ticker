"""`/api/v1/health/live` and `/api/v1/health/ready` (reliability review --
replaces the single `/api/v1/health` from the original spec).

`live` only proves the process is up (no DB call) -- a DB outage should
never make the container report unhealthy and get killed. `ready` is what
the compose healthcheck polls: DB reachable *and* the schema is at the
Alembic head, so `api` never serves traffic against a stale or
half-migrated database (the `migrate` compose service now owns running
migrations; `api` no longer does)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from stockticker.api.migrations import get_head_revision
from stockticker.db import get_api_app_writer_engine
from stockticker.models.health import HealthResponse, ReadyResponse
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ProblemDetail}},
)
async def health_ready() -> ReadyResponse:
    # The connection is acquired here, inside this try, rather than via a
    # FastAPI Depends(...) generator dependency: a dependency that fails to
    # connect raises during FastAPI's own dependency-resolution phase,
    # before the route body (and its try/except) ever runs -- that turned
    # a DB-down 503 into an unhandled 500 (found during review).
    try:
        async with get_api_app_writer_engine().connect() as conn:
            db_revision = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc

    head_revision = get_head_revision()
    if db_revision != head_revision:
        raise HTTPException(
            status_code=503,
            detail=f"database schema at {db_revision!r}, expected head {head_revision!r}",
        )
    return ReadyResponse(status="ok", database="ok", migration="ok")
