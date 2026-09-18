"""The job wrapper every ingest job runs inside (system design §4).

`run_job` never raises -- it always returns a `JobOutcome`. A handler is a
`JobFn`: `async def handler(ctx: JobContext) -> JobResult`, given a
`JobContext` rather than an open connection -- it opens its own short-lived
connections from `ctx.engine`/`ctx.quotes_engine` as needed. The advisory
lock lives on its own dedicated connection, held idle (no open transaction)
for the run's duration, and is never handed to the handler: the handler
cannot accidentally do its DB work *as* the lock connection, and a query
timeout or long transaction in the handler can never threaten the lock.

1. Take `pg_try_advisory_lock(hashtext(job))` on the dedicated lock
   connection. A held lock records `skipped_locked` and sets a
   `rerun_requested` watermark.
2. Mark any pre-existing `running` row for this job `failed` ("orphaned")
   -- we hold the lock, so a `running` row here can only be left over from
   a run that died without releasing it. Checked on every trigger, at any
   age, not only via the startup sweep.
3. Insert an `ingest_runs` row with status `running`, on a short-lived
   connection (never the lock connection).
4. Run the handler. It reports per-item failures in its `JobResult` instead
   of raising for them; if any item failed, the run ends `partial`. A
   handler can raise `JobSkipped` (empty inputs) for `skipped`, or
   `ConfigMissingError` (a required key is unset) for `failed` /
   `config_missing`. Any other exception also ends the run `failed`.
5. Before recording the outcome, ping the lock connection. If it's gone --
   asyncpg raises `InterfaceError` or `ConnectionDoesNotExistError`, never
   `OperationalError` -- the run is instead recorded `failed` /
   `lock_connection_lost`, since nothing the handler wrote can be trusted
   to have happened under an exclusive lock.
6. `rerun_requested`: if set when the run finishes, clear it and run again,
   looping while it keeps getting set, all still under the same lock. Once
   clear, unlock -- then check one more time. Wanting a rerun the instant
   between that last clear-check and the unlock (`_request_rerun` beat
   `pg_try_advisory_lock` in the requester, in the classic ordering the
   race is named for) would otherwise strand the flag with no holder left
   watching it; catching it here and trying to relock closes that window.
   If the lock has since been taken by someone else, this run's own result
   is still returned, and the flag is left for whoever holds it now.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.config import Settings, get_settings
from stockticker.logging import FilteringBoundLogger, get_logger

logger = get_logger(__name__)

RERUN_REQUESTED_KEY = "rerun_requested"

JobRunStatus = Literal["running", "succeeded", "partial", "failed", "skipped_locked", "skipped"]


@dataclass(slots=True)
class FailedItem:
    key: str
    error: str


@dataclass(slots=True)
class JobResult:
    rows_written: int = 0
    failed_items: list[FailedItem] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class JobOutcome:
    status: JobRunStatus
    result: JobResult | None = None
    error: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class JobContext:
    engine: AsyncEngine
    run_id: int
    settings: Settings
    log: FilteringBoundLogger
    quotes_engine: AsyncEngine | None = None


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


JobFn = Callable[[JobContext], Awaitable[JobResult]]


def _is_connection_lost(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", exc)
    return isinstance(
        orig, (asyncpg.exceptions.InterfaceError, asyncpg.exceptions.ConnectionDoesNotExistError)
    )


async def run_job(
    job_name: str,
    fn: JobFn,
    *,
    engine: AsyncEngine,
    quotes_engine: AsyncEngine | None = None,
) -> JobOutcome:
    last_outcome: JobOutcome | None = None
    while True:
        outcome, held = await _try_hold_lock_and_run(engine, quotes_engine, job_name, fn)
        if held:
            assert outcome is not None
            last_outcome = outcome
            if await _rerun_flag_is_set(engine, job_name):
                continue  # raced the unlock below; try to relock once more
            return last_outcome

        if last_outcome is None:
            logger.info("ingest.job.skipped_locked", job=job_name)
            await _record_skipped_locked(engine, job_name)
            await _request_rerun(engine, job_name)
            return JobOutcome(status="skipped_locked")

        # We already ran at least once and honored every rerun we saw while
        # we held the lock; a new one landed in the gap after we unlocked,
        # and by the time we tried to relock someone else had it. Leave the
        # flag for them and report what we actually did.
        await _request_rerun(engine, job_name)
        return last_outcome


async def _try_hold_lock_and_run(
    engine: AsyncEngine, quotes_engine: AsyncEngine | None, job_name: str, fn: JobFn
) -> tuple[JobOutcome | None, bool]:
    lock_conn = await engine.connect()
    try:
        locked = await lock_conn.scalar(
            text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name}
        )
        await lock_conn.commit()  # end the implicit transaction; the connection is now idle
        if not locked:
            return None, False

        await _fail_orphaned_running_rows(engine, job_name)
        outcome = await _run_once(engine, quotes_engine, job_name, fn, lock_conn)
        while await _consume_rerun_flag(engine, job_name):
            logger.info("ingest.job.rerun_requested_honored", job=job_name)
            outcome = await _run_once(engine, quotes_engine, job_name, fn, lock_conn)
        return outcome, True
    finally:
        await _release_lock(lock_conn, job_name)
        await lock_conn.close()


async def _run_once(
    engine: AsyncEngine,
    quotes_engine: AsyncEngine | None,
    job_name: str,
    fn: JobFn,
    lock_conn: AsyncConnection,
) -> JobOutcome:
    started_at = datetime.now(UTC)
    async with engine.connect() as conn:
        run_id = await conn.scalar(
            text(
                "INSERT INTO ingest_runs (job, status, started_at) "
                "VALUES (:job, 'running', :started_at) RETURNING id"
            ),
            {"job": job_name, "started_at": started_at},
        )
        await conn.commit()

    log = logger.bind(job=job_name, run_id=run_id)
    log.info("ingest.job.start")
    ctx = JobContext(
        engine=engine, quotes_engine=quotes_engine, run_id=run_id, settings=get_settings(), log=log
    )

    try:
        result = await fn(ctx)
    except ConfigMissingError as exc:
        log.info("ingest.job.config_missing", missing_keys=exc.missing_keys)
        outcome = JobOutcome(
            status="failed",
            error={"type": "config_missing", "message": str(exc), "missing_keys": exc.missing_keys},
        )
    except JobSkipped as exc:
        log.info("ingest.job.skipped", reason=exc.reason)
        outcome = JobOutcome(status="skipped", error={"type": "skipped", "message": exc.reason})
    except Exception as exc:  # noqa: BLE001 - recorded, never re-raised: run_job never raises
        log.error("ingest.job.failed", error=str(exc))
        outcome = JobOutcome(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
    else:
        error: dict[str, Any] | None = None
        if result.failed_items:
            status: JobRunStatus = "partial"
            error = {
                "type": "partial",
                "items": [{"key": item.key, "error": item.error} for item in result.failed_items],
            }
        else:
            status = "succeeded"
        outcome = JobOutcome(status=status, result=result, error=error)

    if not await _lock_connection_alive(lock_conn):
        log.error("ingest.job.lock_connection_lost")
        outcome = JobOutcome(
            status="failed", error={"type": "lock_connection_lost", "message": "lock connection lost"}
        )

    await _finish_run(engine, run_id, outcome)
    log.info(
        "ingest.job.end",
        status=outcome.status,
        rows_written=outcome.result.rows_written if outcome.result else 0,
        items_failed=len(outcome.result.failed_items) if outcome.result else 0,
    )
    return outcome


async def _lock_connection_alive(lock_conn: AsyncConnection) -> bool:
    try:
        await lock_conn.execute(text("SELECT 1"))
        await lock_conn.commit()
        return True
    except Exception:  # noqa: BLE001 - any failure here means "not alive"; run_job never raises
        return False


async def _fail_orphaned_running_rows(engine: AsyncEngine, job_name: str) -> int:
    async with engine.connect() as conn:
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
    return result.rowcount or 0


async def _release_lock(lock_conn: AsyncConnection, job_name: str) -> None:
    try:
        await lock_conn.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
        await lock_conn.commit()
    except Exception as exc:  # noqa: BLE001 - the connection may already be dead; nothing more to do
        logger.debug("ingest.job.unlock_failed", job=job_name, error=str(exc))


async def _record_skipped_locked(engine: AsyncEngine, job_name: str) -> None:
    now = datetime.now(UTC)
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO ingest_runs (job, status, started_at, finished_at, rows_written, items_failed) "
                "VALUES (:job, 'skipped_locked', :now, :now, 0, 0)"
            ),
            {"job": job_name, "now": now},
        )
        await conn.commit()


async def _request_rerun(engine: AsyncEngine, job_name: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO ingest_watermarks (job, key, value, updated_at) "
                "VALUES (:job, :key, '1', now()) "
                "ON CONFLICT (job, key) DO UPDATE SET value = '1', updated_at = now()"
            ),
            {"job": job_name, "key": RERUN_REQUESTED_KEY},
        )
        await conn.commit()


async def _consume_rerun_flag(engine: AsyncEngine, job_name: str) -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("DELETE FROM ingest_watermarks WHERE job = :job AND key = :key RETURNING value"),
            {"job": job_name, "key": RERUN_REQUESTED_KEY},
        )
        await conn.commit()
        return row.first() is not None


async def _rerun_flag_is_set(engine: AsyncEngine, job_name: str) -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT 1 FROM ingest_watermarks WHERE job = :job AND key = :key"),
            {"job": job_name, "key": RERUN_REQUESTED_KEY},
        )
        return row.first() is not None


async def _finish_run(engine: AsyncEngine, run_id: int, outcome: JobOutcome) -> None:
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "UPDATE ingest_runs SET status = :status, finished_at = :finished_at, "
                "rows_written = :rows_written, items_failed = :items_failed, error = :error "
                "WHERE id = :run_id"
            ),
            {
                "status": outcome.status,
                "finished_at": datetime.now(UTC),
                "rows_written": outcome.result.rows_written if outcome.result else 0,
                "items_failed": len(outcome.result.failed_items) if outcome.result else 0,
                "error": _to_jsonb_param(outcome.error),
                "run_id": run_id,
            },
        )
        await conn.commit()


def _to_jsonb_param(value: dict[str, Any] | None) -> Any:
    import json

    return None if value is None else json.dumps(value)


async def cleanup_orphan_runs_at_startup(engine: AsyncEngine, job_names: Iterable[str]) -> int:
    """Lock-based startup sweep: for each known job name, try its advisory
    lock (nobody else should be running it yet, this early); if acquired,
    fail any leftover `running` row for it. A lock we can't get means
    another process is legitimately running that job right now -- skip it,
    `run_job`'s own per-trigger check will catch a real orphan later."""
    total = 0
    for job_name in job_names:
        conn = await engine.connect()
        try:
            locked = await conn.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
            await conn.commit()
            if not locked:
                continue
            total += await _fail_orphaned_running_rows(engine, job_name)
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
                await conn.commit()
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.debug("ingest.startup_cleanup.unlock_failed", job=job_name, error=str(exc))
            await conn.close()
    if total:
        logger.info("ingest.orphan_runs.cleaned_at_startup", count=total)
    return total


async def ingest_runs_prune(ctx: JobContext) -> JobResult:
    """Retention: `succeeded`/`skipped_locked`/`skipped` rows live 7 days,
    `failed`/`partial` rows live 90 -- `/api/v1/status` still finds a job's
    last success within that window."""
    async with ctx.engine.connect() as conn:
        recent = await conn.execute(
            text(
                "DELETE FROM ingest_runs WHERE status IN ('succeeded', 'skipped_locked', 'skipped') "
                "AND started_at < now() - interval '7 days'"
            )
        )
        old_failures = await conn.execute(
            text(
                "DELETE FROM ingest_runs WHERE status IN ('failed', 'partial') "
                "AND started_at < now() - interval '90 days'"
            )
        )
        await conn.commit()
    return JobResult(rows_written=(recent.rowcount or 0) + (old_failures.rowcount or 0))
