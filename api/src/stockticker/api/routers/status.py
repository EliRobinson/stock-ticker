"""`GET /api/v1/status` (system design §5).

`jobs` enumerates `ingest.registry.JOBS`, not just jobs that happen to have
a row in `ingest_runs` -- a job that has never fired yet still shows up
with `status: null` rather than being silently absent. `missing_keys` is
the union of every registered job's `requires_keys`, so it reports exactly
what's gating *this build's* registered work, not a fixed list of four env
vars regardless of whether anything needs them yet. `market_clock` is
`None` until `stockticker.marketdata.fetch_market_clock` is implemented.
`open_gaps` counts `refetch_requests` rows with `reason = 'gap'` and
`accepted_at IS NULL` -- `gap_check` inserts one per unfilled gap and sets
`accepted_at` once it gives up after 3 attempts (§4), so an open gap is
exactly a row that's neither been filled nor accepted yet.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from stockticker.config import Settings, get_settings
from stockticker.db import get_app_writer_connection
from stockticker.ingest.registry import JOBS
from stockticker.marketdata import fetch_market_clock
from stockticker.models.status import AiStatus, BackfillProgress, JobStatusEntry, StatusResponse

router = APIRouter(tags=["status"])

_RECENT_RUNS_PER_JOB = 50


async def _recent_runs_by_job(conn: AsyncConnection) -> dict[str, list[Row[Any]]]:
    rows = (
        await conn.execute(
            text(
                "SELECT job, status, finished_at, error "
                "FROM (SELECT job, status, finished_at, error, started_at, "
                "      row_number() OVER (PARTITION BY job ORDER BY started_at DESC) AS rn "
                "      FROM ingest_runs) ranked "
                f"WHERE rn <= {_RECENT_RUNS_PER_JOB} ORDER BY job, rn"
            )
        )
    ).all()
    by_job: dict[str, list[Row[Any]]] = defaultdict(list)
    for row in rows:
        by_job[row.job].append(row)
    return by_job


def _job_status_entry(job_name: str, runs: list[Row[Any]]) -> JobStatusEntry:
    if not runs:
        return JobStatusEntry(
            job=job_name,
            status=None,
            finished_at=None,
            last_success_at=None,
            consecutive_failures=0,
            error_summary=None,
        )
    latest = runs[0]
    consecutive_failures = 0
    for run in runs:
        if run.status == "failed":
            consecutive_failures += 1
        else:
            break
    last_success_at = next((run.finished_at for run in runs if run.status == "succeeded"), None)
    error_summary = None
    if latest.error:
        error_summary = latest.error.get("message") or f"{latest.status}: see ingest_runs.error"
    return JobStatusEntry(
        job=job_name,
        status=latest.status,
        finished_at=latest.finished_at,
        last_success_at=last_success_at,
        consecutive_failures=consecutive_failures,
        error_summary=error_summary,
    )


async def _job_statuses(conn: AsyncConnection) -> list[JobStatusEntry]:
    by_job = await _recent_runs_by_job(conn)
    return [_job_status_entry(spec.name, by_job.get(spec.name, [])) for spec in JOBS]


async def _backfill_progress(conn: AsyncConnection) -> BackfillProgress:
    total = await conn.scalar(text("SELECT count(*) FROM listings WHERE is_active"))
    done = await conn.scalar(
        text("SELECT count(*) FROM listings WHERE is_active AND backfill_completed_at IS NOT NULL")
    )
    return BackfillProgress(listings_done=done or 0, listings_total=total or 0)


async def _data_as_of(conn: AsyncConnection) -> datetime | None:
    result: datetime | None = await conn.scalar(text("SELECT max(observed_at) FROM quotes"))
    return result


async def _open_gaps(conn: AsyncConnection) -> int:
    count = await conn.scalar(
        text("SELECT count(*) FROM refetch_requests WHERE reason = 'gap' AND accepted_at IS NULL")
    )
    return count or 0


async def _ai_status(settings: Settings) -> AiStatus | None:
    # stockticker.ai.status.ai_status(settings) is issue #7's agreed
    # contract (the AI chat agent owns it end to end); imported here at
    # call time, not at module level, so this branch keeps working before
    # #7 merges to main and that module exists. Once it does, this starts
    # returning real status with no further change here.
    try:
        from stockticker.ai.status import ai_status
    except ImportError:
        return None
    result: AiStatus = await ai_status(settings)
    return result


@router.get("/status", response_model=StatusResponse)
async def status(
    conn: AsyncConnection = Depends(get_app_writer_connection),
    settings: Settings = Depends(get_settings),
) -> StatusResponse:
    required_keys = {key for spec in JOBS for key in spec.requires_keys}
    return StatusResponse(
        server_time=datetime.now(UTC),
        market_clock=await fetch_market_clock(),
        jobs=await _job_statuses(conn),
        backfill=await _backfill_progress(conn),
        missing_keys=settings.missing_keys(required_keys),
        data_as_of=await _data_as_of(conn),
        open_gaps=await _open_gaps(conn),
        ai=await _ai_status(settings),
    )
