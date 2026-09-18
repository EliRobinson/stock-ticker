from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """`/api/v1/health/live` only: proves the process is up, no DB call."""

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    """`/api/v1/health/ready`: DB reachable and schema at the Alembic head."""

    status: Literal["ok"]
    database: Literal["ok"]
    migration: Literal["ok"]
