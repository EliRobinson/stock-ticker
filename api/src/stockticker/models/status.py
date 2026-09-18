from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

JobRunStatus = Literal["running", "succeeded", "partial", "failed", "skipped_locked", "skipped"]


class MarketClock(BaseModel):
    """Null until the Alpaca agent wires up `fetch_market_clock` (see marketdata.py)."""

    is_open: bool
    next_open: datetime
    next_close: datetime


class JobStatusEntry(BaseModel):
    job: str
    # Null means the job is registered (system design §4 / worker.JOBS) but
    # has never run yet -- distinct from any status ingest_runs records.
    status: JobRunStatus | None
    finished_at: datetime | None
    # The most recent `succeeded` finished_at seen in the retained window.
    # ingest_runs_prune keeps `succeeded` rows for 7 days, so this can go
    # stale (None) for a job that hasn't succeeded recently even if it once did.
    last_success_at: datetime | None
    consecutive_failures: int
    error_summary: str | None


class BackfillProgress(BaseModel):
    listings_done: int
    listings_total: int


class AiStatus(BaseModel):
    """Populated once the AI chat agent's `ai_usage` table (migration
    0002+) and pricing module exist; see `_ai_status` in
    `api/routers/status.py` for exactly what's real today versus a
    placeholder."""

    spend_usd: float
    limit_usd: float
    enabled: bool


class StatusResponse(BaseModel):
    server_time: datetime
    market_clock: MarketClock | None
    jobs: list[JobStatusEntry]
    backfill: BackfillProgress
    missing_keys: list[str]
    data_as_of: datetime | None
    open_gaps: int
    ai: AiStatus
