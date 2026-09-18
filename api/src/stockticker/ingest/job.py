"""The job wrapper every ingest job runs inside (system design §4).

`run_job` never raises -- it always returns a `JobOutcome`, even if the
database is unreachable before a lock could be taken at all. A handler is a
`JobFn`: `async def handler(ctx: JobContext) -> JobResult`, given a
`JobContext` rather than an open connection -- it opens its own short-lived
connections from `ctx.engine`/`ctx.quotes_engine` as needed, and can call
`await ctx.lock_alive()` to check early whether it should abort a long
operation. `run_job` takes the full `JobSpec` (not a bare name/handler
pair): it applies `requires_keys` and `trading_days_only` itself, and picks
the lock/handler engine from `spec.engine`.

The advisory lock lives on its own dedicated connection (`advisory_lock`,
below), held idle (no open transaction) for the run's duration, and is
never handed to the handler: the handler cannot accidentally do its DB
work *as* the lock connection, and a query timeout or long transaction in
the handler can never threaten the lock.

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
   `config_missing`. Any other exception also ends the run `failed` /
   `<exception class name>`; anything `run_job`'s own bookkeeping can't
   recover from (the DB is down, the lock connection never opens) ends it
   `failed` / `infra` instead of raising.
5. Before recording the outcome, ping the lock connection. If it's gone --
   asyncpg raises `InterfaceError` or `ConnectionDoesNotExistError`, never
   `OperationalError` -- the run is instead recorded `failed` /
   `lock_connection_lost`, since nothing the handler wrote can be trusted
   to have happened under an exclusive lock. The run stops there: it does
   not enter the rerun-honoring loop (a dead connection may have already
   lost the advisory lock itself), and leaves any `rerun_requested` flag
   for the next holder.
6. `rerun_requested`: if set when the run finishes, clear it and run again,
   looping while it keeps getting set, all still under the same lock. Once
   clear, unlock -- then check one more time. Wanting a rerun the instant
   between that last clear-check and the unlock (`_request_rerun` beat
   `pg_try_advisory_lock` in the requester, in the classic ordering the
   race is named for) would otherwise strand the flag with no holder left
   watching it; catching it here and trying to relock closes that window.
   If the lock has since been taken by someone else, this run's own result
   is still returned, and the flag is left for whoever holds it now.
7. A failed unlock (the connection is already dead) invalidates the pooled
   connection instead of returning a broken one to the pool, and logs a
   warning -- the same in the startup orphan sweep.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.config import RequiredKey, Settings, get_settings
from stockticker.ingest.watermarks import read_watermark, write_watermark
from stockticker.logging import FilteringBoundLogger, get_logger
from stockticker.models.status import JobRunStatus
from stockticker.timeutil import today_ny

logger = get_logger(__name__)

RERUN_REQUESTED_KEY = "rerun_requested"

# A laptop that slept through a cron firing still runs it once on wake;
# an interval job (polling) just catches the next tick instead.
CRON_MISFIRE_GRACE_SECONDS = 6 * 60 * 60
INTERVAL_MISFIRE_GRACE_SECONDS = 5


@dataclass(slots=True)
class FailedItem:
    key: str
    error: str


@dataclass(slots=True)
class JobResult:
    rows_written: int = 0
    failed_items: list[FailedItem] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class JobError:
    type: str
    message: str
    missing_keys: list[str] | None = None
    items: list[dict[str, str]] | None = None

    def to_jsonb(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "message": self.message}
        if self.missing_keys is not None:
            payload["missing_keys"] = self.missing_keys
        if self.items is not None:
            payload["items"] = self.items
        return payload


@dataclass(slots=True, frozen=True)
class JobOutcome:
    status: JobRunStatus
    result: JobResult | None = None
    error: JobError | None = None


@dataclass(slots=True, frozen=True)
class JobContext:
    engine: AsyncEngine
    quotes_engine: AsyncEngine
    run_id: int
    settings: Settings
    log: FilteringBoundLogger
    _lock_conn: AsyncConnection = field(repr=False, compare=False)

    async def lock_alive(self) -> bool:
        """A long-running handler can check this periodically and abort
        early if the advisory lock connection has died -- `run_job` checks
        it again unconditionally before recording the outcome regardless."""
        return await _lock_connection_alive(self._lock_conn)


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


@dataclass(slots=True, frozen=True)
class JobSpec:
    name: str
    trigger: BaseTrigger
    handler: JobFn
    trading_days_only: bool = False
    requires_keys: tuple[RequiredKey, ...] = ()
    misfire_grace_time: int | None = None  # None -> derived from trigger type
    # Names of jobs that, after they finish (success or not -- run_job
    # never raises), should immediately run this one too, via run_job,
    # before the scheduler moves on. E.g. market_caps_rebuild's
    # runs_after=("bars_daily", "edgar_sync") (system design §4).
    runs_after: tuple[str, ...] = ()
    # "quotes" pins both the advisory lock and ctx.engine to the small,
    # dedicated quotes engine (db.get_quotes_engine()) instead of the
    # shared worker pool, so quotes_poll's lock-taking never queues behind
    # the rest of the worker's jobs. Only quotes_poll should ever set this.
    engine: Literal["default", "quotes"] = "default"

    def resolved_misfire_grace_time(self) -> int:
        if self.misfire_grace_time is not None:
            return self.misfire_grace_time
        return (
            CRON_MISFIRE_GRACE_SECONDS
            if isinstance(self.trigger, CronTrigger)
            else INTERVAL_MISFIRE_GRACE_SECONDS
        )


@asynccontextmanager
async def advisory_lock(engine: AsyncEngine, job_name: str) -> AsyncIterator[tuple[AsyncConnection, bool]]:
    """Yields `(conn, held)`. `conn` is a dedicated connection, idle (no
    open transaction) once this yields; `held` says whether the advisory
    lock was actually acquired. Unlocking on the way out invalidates the
    connection (rather than returning a possibly-broken one to the pool)
    and logs a warning if the unlock itself fails."""
    conn = await engine.connect()
    held = False
    try:
        held = bool(await conn.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name}))
        await conn.commit()  # end the implicit transaction; the connection is now idle
        yield conn, held
    finally:
        if held:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
                await conn.commit()
            except Exception as exc:  # noqa: BLE001 - the connection may already be dead
                logger.warning("ingest.job.unlock_failed", job=job_name, error=str(exc))
                await conn.invalidate()
        await conn.close()


async def run_job(spec: JobSpec, *, engine: AsyncEngine, quotes_engine: AsyncEngine) -> JobOutcome:
    """Never raises. `spec.engine == "quotes"` uses `quotes_engine` for
    both the lock and `ctx.engine`; every other job uses `engine`."""
    try:
        return await _run_job_inner(spec, engine=engine, quotes_engine=quotes_engine)
    except Exception as exc:  # noqa: BLE001 - run_job must never raise
        logger.error("ingest.job.infra_error", job=spec.name, error=str(exc))
        return JobOutcome(status="failed", error=JobError(type="infra", message=str(exc)))


async def _run_job_inner(spec: JobSpec, *, engine: AsyncEngine, quotes_engine: AsyncEngine) -> JobOutcome:
    job_engine = quotes_engine if spec.engine == "quotes" else engine
    last_outcome: JobOutcome | None = None

    while True:
        async with advisory_lock(job_engine, spec.name) as (lock_conn, held):
            if not held:
                if last_outcome is None:
                    logger.info("ingest.job.skipped_locked", job=spec.name)
                    await _record_skipped_locked(job_engine, spec.name)
                    await _request_rerun(job_engine, spec.name)
                    return JobOutcome(status="skipped_locked")
                # Already ran at least once and honored every rerun seen
                # while holding the lock; a new one landed in the gap after
                # unlocking, and by the time of the relock attempt someone
                # else had it. Leave the flag for them.
                await _request_rerun(job_engine, spec.name)
                return last_outcome

            await _fail_orphaned_running_rows(job_engine, spec.name)
            outcome = await _run_once(spec, job_engine, quotes_engine, lock_conn)
            last_outcome = outcome
            if outcome.error is not None and outcome.error.type == "lock_connection_lost":
                # Don't trust a dead connection to still hold the lock, or
                # try to touch the DB again through it.
                return outcome
            while await _consume_rerun_flag(job_engine, spec.name):
                logger.info("ingest.job.rerun_requested_honored", job=spec.name)
                outcome = await _run_once(spec, job_engine, quotes_engine, lock_conn)
                last_outcome = outcome
                if outcome.error is not None and outcome.error.type == "lock_connection_lost":
                    return outcome

        if not await _rerun_flag_is_set(job_engine, spec.name):
            return last_outcome
        # else: raced the unlock above; loop back and try to relock once more.


async def _run_once(
    spec: JobSpec, job_engine: AsyncEngine, quotes_engine: AsyncEngine, lock_conn: AsyncConnection
) -> JobOutcome:
    started_at = datetime.now(UTC)
    async with job_engine.connect() as conn:
        run_id = await conn.scalar(
            text(
                "INSERT INTO ingest_runs (job, status, started_at) "
                "VALUES (:job, 'running', :started_at) RETURNING id"
            ),
            {"job": spec.name, "started_at": started_at},
        )
        await conn.commit()

    log = logger.bind(job=spec.name, run_id=run_id)
    log.info("ingest.job.start")
    settings = get_settings()
    ctx = JobContext(
        engine=job_engine,
        quotes_engine=quotes_engine,
        run_id=run_id,
        settings=settings,
        log=log,
        _lock_conn=lock_conn,
    )

    try:
        missing = [key.value for key in spec.requires_keys if settings.is_missing(key)]
        if missing:
            raise ConfigMissingError(missing)
        if spec.trading_days_only:
            async with job_engine.connect() as conn:
                is_trading_day = await conn.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM trading_days WHERE trade_date = :d)"),
                    {"d": today_ny()},
                )
            if not is_trading_day:
                raise JobSkipped(f"{today_ny()} is not a Trading Day")
        result = await spec.handler(ctx)
    except ConfigMissingError as exc:
        log.info("ingest.job.config_missing", missing_keys=exc.missing_keys)
        outcome = JobOutcome(
            status="failed",
            error=JobError(type="config_missing", message=str(exc), missing_keys=exc.missing_keys),
        )
    except JobSkipped as exc:
        log.info("ingest.job.skipped", reason=exc.reason)
        outcome = JobOutcome(status="skipped", error=JobError(type="skipped", message=exc.reason))
    except Exception as exc:  # noqa: BLE001 - recorded, never re-raised: run_job never raises
        log.error("ingest.job.failed", error=str(exc))
        outcome = JobOutcome(status="failed", error=JobError(type=type(exc).__name__, message=str(exc)))
    else:
        error: JobError | None = None
        if result.failed_items:
            status: JobRunStatus = "partial"
            error = JobError(
                type="partial",
                message=f"{len(result.failed_items)} item(s) failed",
                items=[{"key": item.key, "error": item.error} for item in result.failed_items],
            )
        else:
            status = "succeeded"
        outcome = JobOutcome(status=status, result=result, error=error)

    if not await _lock_connection_alive(lock_conn):
        log.error("ingest.job.lock_connection_lost")
        outcome = JobOutcome(
            status="failed",
            error=JobError(type="lock_connection_lost", message="lock connection lost"),
        )

    await _finish_run(job_engine, run_id, outcome)
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
        await write_watermark(conn, job_name, RERUN_REQUESTED_KEY, "1")
        await conn.commit()


async def _consume_rerun_flag(engine: AsyncEngine, job_name: str) -> bool:
    """Atomic test-and-clear: `watermarks.delete_watermarks` doesn't report
    whether a row existed, so this stays a direct `DELETE ... RETURNING`
    rather than a `read_watermark` + `delete_watermarks` pair, which would
    race another writer between the two calls."""
    async with engine.connect() as conn:
        row = await conn.execute(
            text("DELETE FROM ingest_watermarks WHERE job = :job AND key = :key RETURNING value"),
            {"job": job_name, "key": RERUN_REQUESTED_KEY},
        )
        await conn.commit()
        return row.first() is not None


async def _rerun_flag_is_set(engine: AsyncEngine, job_name: str) -> bool:
    async with engine.connect() as conn:
        return await read_watermark(conn, job_name, RERUN_REQUESTED_KEY) is not None


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
                "error": _to_jsonb_param(outcome.error.to_jsonb() if outcome.error else None),
                "run_id": run_id,
            },
        )
        await conn.commit()


def _to_jsonb_param(value: dict[str, Any] | None) -> Any:
    import json

    return None if value is None else json.dumps(value)


async def cleanup_orphan_runs_at_startup(engine: AsyncEngine, job_names: list[str]) -> int:
    """Lock-based startup sweep: for each known job name, try its advisory
    lock (nobody else should be running it yet, this early); if acquired,
    fail any leftover `running` row for it. A lock we can't get means
    another process is legitimately running that job right now -- skip it,
    `run_job`'s own per-trigger check will catch a real orphan later."""
    total = 0
    for job_name in job_names:
        async with advisory_lock(engine, job_name) as (_conn, held):
            if not held:
                continue
            total += await _fail_orphaned_running_rows(engine, job_name)
    if total:
        logger.info("ingest.orphan_runs.cleaned_at_startup", count=total)
    return total
