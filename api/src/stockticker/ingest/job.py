"""The job wrapper every ingest job runs inside (system design §4, plus the
reliability review folded in below).

1. Open one dedicated connection for the whole run and hold
   `pg_try_advisory_lock(hashtext(job))` on it (a session-level lock) for as
   long as the run lasts; a held lock records `skipped_locked` and sets a
   `rerun_requested` watermark for the current holder to pick up.
2. Before starting, mark any pre-existing `running` row for this job
   `failed` ("orphaned") -- we hold the lock, so a `running` row here can
   only be left over from a run that died without releasing it. This check
   runs on every trigger, not just at worker startup, so an orphan is
   caught the moment the job is next attempted, at any age.
3. Insert an `ingest_runs` row with status `running`.
4. Run the job function. It reports per-item failures in its `JobResult`
   instead of raising for them, so one bad symbol/CIK doesn't abort the run;
   if any item failed, the run ends `partial`.
5. A job can raise `JobSkipped` (empty inputs -- no listings, no trading
   days) for a `skipped` run, or `ConfigMissingError` (a required provider
   key is unset) for a `failed` run tagged `config_missing`. Any other
   uncaught exception also ends the run `failed`; losing the connection
   itself (not just the query) ends it `failed` / `lock_connection_lost`,
   recorded over a fresh connection since the original one is unusable.
6. If a `rerun_requested` watermark is set for this job when the run
   finishes, clear it and run once more (bounded to one extra pass) before
   releasing the lock -- the run that was `skipped_locked` gets its result
   after all, without a second concurrent attempt.
7. `cleanup_orphan_runs` (called once, at worker startup) is a coarser,
   time-based backstop for jobs that might not fire again soon.

Usage, from a job module::

    async def my_job(conn: AsyncConnection) -> JobResult:
        ...
        return JobResult(rows_written=n, failed_items=[FailedItem(key=sym, error=str(exc))])

    await run_job("my_job", my_job, engine=get_app_writer_engine())
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.logging import get_logger

logger = get_logger(__name__)

ORPHAN_RUN_TIMEOUT = timedelta(hours=1)
RERUN_REQUESTED_KEY = "rerun_requested"


@dataclass(slots=True)
class FailedItem:
    key: str
    error: str


@dataclass(slots=True)
class JobResult:
    rows_written: int = 0
    failed_items: list[FailedItem] = field(default_factory=list)


class ConfigMissingError(Exception):
    """Raise when a job needs a provider key that Settings doesn't have."""

    def __init__(self, missing_keys: list[str]) -> None:
        self.missing_keys = missing_keys
        super().__init__(f"missing keys: {', '.join(missing_keys)}")


class JobSkipped(Exception):
    """Raise when a job has nothing to do yet (no listings, no trading
    days) -- distinct from failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


JobFn = Callable[[AsyncConnection], Awaitable[JobResult]]


async def run_job(job_name: str, fn: JobFn, *, engine: AsyncEngine) -> JobResult | None:
    """Run `fn` under the job wrapper. Returns `None` if the job was skipped
    because another process holds its advisory lock (a rerun is then queued
    for that holder)."""
    async with engine.connect() as conn:
        locked = await conn.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
        await conn.commit()

        if not locked:
            logger.info("ingest.job.skipped_locked", job=job_name)
            now = datetime.now(UTC)
            await conn.execute(
                text(
                    "INSERT INTO ingest_runs (job, status, started_at, finished_at, "
                    "rows_written, items_failed) VALUES (:job, 'skipped_locked', :now, :now, 0, 0)"
                ),
                {"job": job_name, "now": now},
            )
            await _request_rerun(conn, job_name)
            await conn.commit()
            return None

        try:
            await _fail_orphaned_running_rows(conn, job_name)
            result = await _run_once(conn, job_name, fn)
            if await _rerun_was_requested(conn, job_name):
                logger.info("ingest.job.rerun_requested_honored", job=job_name)
                result = await _run_once(conn, job_name, fn)
            return result
        finally:
            await _release_lock(conn, job_name)


async def _fail_orphaned_running_rows(conn: AsyncConnection, job_name: str) -> None:
    result = await conn.execute(
        text(
            "UPDATE ingest_runs SET status = 'failed', finished_at = now(), "
            "error = :error WHERE job = :job AND status = 'running'"
        ),
        {"job": job_name, "error": _to_jsonb_param({"type": "orphaned", "message": "orphaned"})},
    )
    await conn.commit()
    if result.rowcount:
        logger.info("ingest.job.orphan_marked_failed", job=job_name, count=result.rowcount)


async def _run_once(conn: AsyncConnection, job_name: str, fn: JobFn) -> JobResult:
    started_at = datetime.now(UTC)
    run_id = await conn.scalar(
        text(
            "INSERT INTO ingest_runs (job, status, started_at) "
            "VALUES (:job, 'running', :started_at) RETURNING id"
        ),
        {"job": job_name, "started_at": started_at},
    )
    await conn.commit()
    logger.info("ingest.job.start", job=job_name, run_id=run_id)

    try:
        result = await fn(conn)
    except ConfigMissingError as exc:
        await conn.rollback()
        logger.info("ingest.job.config_missing", job=job_name, run_id=run_id, missing_keys=exc.missing_keys)
        await _finish_run(
            conn,
            run_id,
            status="failed",
            rows_written=0,
            items_failed=0,
            error={"type": "config_missing", "message": str(exc), "missing_keys": exc.missing_keys},
        )
        await conn.commit()
        return JobResult()
    except JobSkipped as exc:
        await conn.rollback()
        logger.info("ingest.job.skipped", job=job_name, run_id=run_id, reason=exc.reason)
        await _finish_run(
            conn,
            run_id,
            status="skipped",
            rows_written=0,
            items_failed=0,
            error={"type": "skipped", "message": exc.reason},
        )
        await conn.commit()
        return JobResult()
    except OperationalError as exc:
        logger.error("ingest.job.lock_connection_lost", job=job_name, run_id=run_id, error=str(exc))
        await _record_failure_resilient(conn.engine, run_id, "lock_connection_lost", "lock connection lost")
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        await conn.rollback()
        logger.error("ingest.job.failed", job=job_name, run_id=run_id, error=str(exc))
        await _finish_run(
            conn,
            run_id,
            status="failed",
            rows_written=0,
            items_failed=0,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        await conn.commit()
        raise
    else:
        status = "partial" if result.failed_items else "succeeded"
        error: dict[str, Any] | None = None
        if result.failed_items:
            error = {
                "type": "partial",
                "items": [{"key": item.key, "error": item.error} for item in result.failed_items],
            }
        await _finish_run(
            conn,
            run_id,
            status=status,
            rows_written=result.rows_written,
            items_failed=len(result.failed_items),
            error=error,
        )
        await conn.commit()
        logger.info(
            "ingest.job.end",
            job=job_name,
            run_id=run_id,
            status=status,
            rows_written=result.rows_written,
            items_failed=len(result.failed_items),
        )
        return result


async def _release_lock(conn: AsyncConnection, job_name: str) -> None:
    try:
        await conn.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
        await conn.commit()
    except Exception as exc:  # noqa: BLE001 - the connection may already be dead; nothing more to do
        logger.debug("ingest.job.unlock_failed", job=job_name, error=str(exc))


async def _request_rerun(conn: AsyncConnection, job_name: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO ingest_watermarks (job, key, value, updated_at) "
            "VALUES (:job, :key, '1', now()) "
            "ON CONFLICT (job, key) DO UPDATE SET value = '1', updated_at = now()"
        ),
        {"job": job_name, "key": RERUN_REQUESTED_KEY},
    )


async def _rerun_was_requested(conn: AsyncConnection, job_name: str) -> bool:
    row = await conn.execute(
        text("DELETE FROM ingest_watermarks WHERE job = :job AND key = :key RETURNING value"),
        {"job": job_name, "key": RERUN_REQUESTED_KEY},
    )
    await conn.commit()
    return row.first() is not None


async def _finish_run(
    conn: AsyncConnection,
    run_id: int,
    *,
    status: str,
    rows_written: int,
    items_failed: int,
    error: dict[str, Any] | None,
) -> None:
    await conn.execute(
        text(
            "UPDATE ingest_runs SET status = :status, finished_at = :finished_at, "
            "rows_written = :rows_written, items_failed = :items_failed, error = :error "
            "WHERE id = :run_id"
        ),
        {
            "status": status,
            "finished_at": datetime.now(UTC),
            "rows_written": rows_written,
            "items_failed": items_failed,
            "error": _to_jsonb_param(error),
            "run_id": run_id,
        },
    )


async def _record_failure_resilient(engine: AsyncEngine, run_id: int, error_type: str, message: str) -> None:
    """Best-effort: write the failure over a *fresh* connection, since the
    one the run was using may itself be the thing that broke."""
    try:
        async with engine.connect() as fresh:
            await _finish_run(
                fresh,
                run_id,
                status="failed",
                rows_written=0,
                items_failed=0,
                error={"type": error_type, "message": message},
            )
            await fresh.commit()
    except Exception as exc:  # noqa: BLE001 - truly best-effort
        logger.error("ingest.job.failure_record_failed", run_id=run_id, error=str(exc))


def _to_jsonb_param(value: dict[str, Any] | None) -> Any:
    import json

    return None if value is None else json.dumps(value)


async def cleanup_orphan_runs(conn: AsyncConnection) -> int:
    """Coarse, time-based backstop: mark `running` rows older than
    `ORPHAN_RUN_TIMEOUT` as `failed`. Call once, at worker startup. The
    per-trigger check in `run_job` (`_fail_orphaned_running_rows`) is the
    primary mechanism and catches an orphan immediately, at any age, the
    next time that job fires; this covers a job that might not fire again
    soon."""
    cutoff = datetime.now(UTC) - ORPHAN_RUN_TIMEOUT
    result = await conn.execute(
        text(
            "UPDATE ingest_runs SET status = 'failed', finished_at = now(), "
            'error = \'{"type": "orphaned", "message": "run exceeded 1h with no completion"}\'::jsonb '
            "WHERE status = 'running' AND started_at < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    await conn.commit()
    count = result.rowcount or 0
    if count:
        logger.info("ingest.orphan_runs.cleaned", count=count)
    return count
