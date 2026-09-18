"""`/api/v1/health/live` and `/api/v1/health/ready` (reliability review --
replaces the single `/api/v1/health` from the original spec).

`live` only proves the process is up (no DB call) -- a DB outage should
never make the container report unhealthy and get killed. `ready` is what
the compose healthcheck polls: DB reachable *and* the schema is at the
Alembic head, so `api` never serves traffic against a stale or
half-migrated database (the `migrate` compose service now owns running
migrations; `api` no longer does)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.api.migrations import get_head_revision
from stockticker.db import get_app_writer_connection
from stockticker.models.health import HealthResponse
from stockticker.models.problem import ProblemDetail

router = APIRouter(tags=["health"])


class ReadyResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    migration: Literal["ok"]


@router.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ProblemDetail}},
)
async def health_ready(conn: AsyncConnection = Depends(get_app_writer_connection)) -> ReadyResponse:
    try:
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
