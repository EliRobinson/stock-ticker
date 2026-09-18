"""Startup-chain behaviour for `bars_backfill` (issue #38): loop until idle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

from stockticker.ingest.job import JobError, JobOutcome, JobResult, JobSpec
from stockticker.worker import _run_startup_job


def _spec(name: str) -> JobSpec:
    async def _handler(_ctx: object) -> JobResult:  # pragma: no cover - never called
        return JobResult()

    return JobSpec(name=name, trigger=CronTrigger(hour=0, minute=0), handler=_handler)


@pytest.mark.parametrize(
    ("outcomes", "expected_calls"),
    [
        (
            [
                JobOutcome(status="succeeded", result=JobResult(rows_written=50)),
                JobOutcome(status="succeeded", result=JobResult(rows_written=50)),
                JobOutcome(status="skipped", error=JobError(type="skipped", message="done")),
            ],
            3,
        ),
        (
            [JobOutcome(status="failed", error=JobError(type="config_missing", message="no keys"))],
            1,
        ),
        (
            [JobOutcome(status="skipped", error=JobError(type="skipped", message="nothing"))],
            1,
        ),
    ],
)
async def test_bars_backfill_startup_loops_until_idle(
    outcomes: list[JobOutcome], expected_calls: int
) -> None:
    run_job = AsyncMock(side_effect=outcomes)

    with patch("stockticker.worker.run_job", run_job):
        await _run_startup_job(_spec("bars_backfill"), AsyncMock(), AsyncMock())

    assert run_job.await_count == expected_calls


async def test_other_startup_jobs_run_once() -> None:
    run_job = AsyncMock(return_value=JobOutcome(status="succeeded", result=JobResult(rows_written=1)))

    with patch("stockticker.worker.run_job", run_job):
        await _run_startup_job(_spec("constituents_sync"), MagicMock(), MagicMock())

    assert run_job.await_count == 1
