"""`GET /api/v1/status` (system design §5).

`jobs` enumerates `worker.JOBS` (the registry), not just jobs that happen to
have a row in `ingest_runs` -- a job that has never fired yet still shows up
with `status: null` rather than being silently absent. `market_clock` is
`None` until `stockticker.marketdata.fetch_market_clock` is implemented.
`open_gaps` reads the latest `gap_check` run's `items_failed`, since the
schema keeps no dedicated gaps table -- `gap_check` (§4) is the only writer.
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
from stockticker.marketdata import fetch_market_clock
from stockticker.models.status import BackfillProgress, JobStatusEntry, StatusResponse
from stockticker.worker import JOBS, register_default_jobs

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
    register_default_jobs()  # idempotent; ensures JOBS is populated even if worker.main() never ran here
    by_job = await _recent_runs_by_job(conn)
    return [_job_status_entry(spec.name, by_job.get(spec.name, [])) for spec in JOBS]


async def _backfill_progress(conn: AsyncConnection) -> BackfillProgress:
    total = await conn.scalar(text("SELECT count(*) FROM listings WHERE is_active"))
    done = await conn.scalar(
        text(
            "SELECT count(*) FROM listings l WHERE l.is_active "
            "AND EXISTS (SELECT 1 FROM daily_bars b WHERE b.symbol = l.symbol)"
        )
    )
    return BackfillProgress(listings_done=done or 0, listings_total=total or 0)


async def _data_as_of(conn: AsyncConnection) -> datetime | None:
    result: datetime | None = await conn.scalar(text("SELECT max(observed_at) FROM quotes"))
    return result


async def _open_gaps(conn: AsyncConnection) -> int:
    row = (
        await conn.execute(
            text(
                "SELECT items_failed FROM ingest_runs WHERE job = 'gap_check' "
                "ORDER BY started_at DESC LIMIT 1"
            )
        )
    ).first()
    return row.items_failed if row else 0


@router.get("/status", response_model=StatusResponse)
async def status(
    conn: AsyncConnection = Depends(get_app_writer_connection),
    settings: Settings = Depends(get_settings),
) -> StatusResponse:
    return StatusResponse(
        server_time=datetime.now(UTC),
        market_clock=await fetch_market_clock(),
        jobs=await _job_statuses(conn),
        backfill=await _backfill_progress(conn),
        missing_keys=settings.missing_keys(),
        data_as_of=await _data_as_of(conn),
        open_gaps=await _open_gaps(conn),
    )
