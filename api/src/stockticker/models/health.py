from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """`/api/v1/health/live` only: proves the process is up, no DB call."""

    status: Literal["ok"]
