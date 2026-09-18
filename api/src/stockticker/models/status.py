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
    """Owned end to end by the AI chat agent's `stockticker.ai.status.
    ai_status(settings)` (issue #7's agreed contract) -- this model just
    gives it a shape to return. `StatusResponse.ai` is null until that
    module exists and `api/routers/status.py` calls it."""

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
    # Null until stockticker.ai.status.ai_status exists (issue #7, agreed
    # contract) and the router wires it in.
    ai: AiStatus | None
