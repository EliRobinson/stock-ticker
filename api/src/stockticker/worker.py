"""The ingest worker process: an APScheduler `AsyncIOScheduler` running in
`America/New_York`, driven by a declarative job registry (`JOBS`).

Register a job from another module::

    from stockticker.worker import JobSpec, register
    from apscheduler.triggers.cron import CronTrigger

    register(JobSpec(
        name="constituents_sync",
        trigger=CronTrigger(hour=6, minute=0),
        handler=constituents_sync,
        requires_keys=(),
    ))

then import that module from `main()` below (see the comment there) so the
`register(...)` call actually runs. `register` wraps the handler with the
job wrapper (`run_job`: advisory lock + `ingest_runs` lifecycle), the
`requires_keys` check (raises `ConfigMissingError`, recorded `failed` /
`config_missing`, handler never called), and the `trading_days_only` check
(raises `JobSkipped` on a non-Trading-Day) automatically -- job authors only
write the handler body.

At startup, before the recurring schedule is registered, `run_startup_chain`
runs `STARTUP_CHAIN` once, each step waiting for the previous one, so the
first real ingest of the night has its inputs ready (`bars_backfill` needs
Listings from `constituents_sync`, `market_caps_rebuild` needs both bars and
shares). A step names a job that may not be registered yet in this PR
(constituents_sync et al. land with the ingest agents) -- it is skipped with
a log line, not an error, so this file needs no edit when those jobs land.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.config import get_settings
from stockticker.db import dispose_engines, get_app_writer_engine
from stockticker.ingest.job import (
    ConfigMissingError,
    JobFn,
    JobResult,
    JobSkipped,
    cleanup_orphan_runs,
    run_job,
)
from stockticker.logging import configure_logging, get_logger
from stockticker.timeutil import NY_TZ, today_ny

logger = get_logger(__name__)

SCHEDULER_TIMEZONE = NY_TZ
JOB_DEFAULTS = {"coalesce": True, "misfire_grace_time": 5}

# A laptop that slept through a cron firing still runs it once on wake;
# an interval job (polling) just catches the next tick instead.
CRON_MISFIRE_GRACE_SECONDS = 6 * 60 * 60
INTERVAL_MISFIRE_GRACE_SECONDS = 5

# Worker liveness for the compose healthcheck: touched every 15s, stale
# past 60s. Not an ingest_runs job -- pure process liveness.
HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 15

WORKER_APP_WRITER_POOL_SIZE = 6


@dataclass(slots=True, frozen=True)
class JobSpec:
    name: str
    trigger: BaseTrigger
    handler: JobFn
    trading_days_only: bool = False
    requires_keys: tuple[str, ...] = ()
    misfire_grace_time: int | None = None  # None -> derived from trigger type

    def resolved_misfire_grace_time(self) -> int:
        if self.misfire_grace_time is not None:
            return self.misfire_grace_time
        return (
            CRON_MISFIRE_GRACE_SECONDS
            if isinstance(self.trigger, CronTrigger)
            else INTERVAL_MISFIRE_GRACE_SECONDS
        )


JOBS: list[JobSpec] = []


def register(spec: JobSpec) -> None:
    if any(existing.name == spec.name for existing in JOBS):
        raise ValueError(f"job {spec.name!r} is already registered")
    JOBS.append(spec)


# Job names other agents' modules register (issue #4 and friends). A step
# that isn't registered yet is skipped, not an error -- see run_startup_chain.
STARTUP_CHAIN: list[str | tuple[str, ...]] = [
    "constituents_sync",
    "calendar_sync",
    ("bars_backfill", "edgar_sync"),
    "market_caps_rebuild",
]


def _wrap_handler(spec: JobSpec) -> JobFn:
    async def wrapped(conn: AsyncConnection) -> JobResult:
        missing = [key for key in spec.requires_keys if key in get_settings().missing_keys()]
        if missing:
            raise ConfigMissingError(missing)
        if spec.trading_days_only:
            is_trading_day = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM trading_days WHERE trade_date = :d)"),
                {"d": today_ny()},
            )
            if not is_trading_day:
                raise JobSkipped(f"{today_ny()} is not a Trading Day")
        return await spec.handler(conn)

    return wrapped


async def run_startup_chain(engine: AsyncEngine) -> None:
    by_name = {spec.name: spec for spec in JOBS}
    for step in STARTUP_CHAIN:
        names = (step,) if isinstance(step, str) else step
        for name in names:
            if name not in by_name:
                logger.debug("startup_chain.step_not_registered", job=name)
        specs = [by_name[name] for name in names if name in by_name]
        if not specs:
            continue
        logger.info("startup_chain.step", jobs=[spec.name for spec in specs])
        await asyncio.gather(*(run_job(spec.name, _wrap_handler(spec), engine=engine) for spec in specs))


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE, job_defaults=JOB_DEFAULTS)


def _schedule(scheduler: AsyncIOScheduler, spec: JobSpec, engine: AsyncEngine) -> None:
    wrapped = _wrap_handler(spec)

    async def _runner() -> None:
        await run_job(spec.name, wrapped, engine=engine)

    scheduler.add_job(
        _runner,
        trigger=spec.trigger,
        id=spec.name,
        replace_existing=True,
        misfire_grace_time=spec.resolved_misfire_grace_time(),
    )


def _touch_heartbeat_file() -> None:
    HEARTBEAT_FILE.touch()


def _start_heartbeat_file_writer(scheduler: AsyncIOScheduler) -> None:
    _touch_heartbeat_file()  # written immediately so the healthcheck doesn't fail before the first tick
    scheduler.add_job(
        _touch_heartbeat_file,
        IntervalTrigger(seconds=HEARTBEAT_INTERVAL_SECONDS),
        id="_heartbeat_file",
        replace_existing=True,
    )


async def noop_heartbeat(conn: AsyncConnection) -> JobResult:
    """Example job: proves the scheduler, the advisory lock, and the
    `ingest_runs` lifecycle work end to end. Real jobs replace this pattern."""
    logger.debug("noop_heartbeat.tick")
    return JobResult(rows_written=0)


async def ingest_runs_prune(conn: AsyncConnection) -> JobResult:
    """Retention (reliability review): `succeeded`/`skipped_locked`/
    `skipped` rows live 7 days, `failed`/`partial` rows live 90 -- `/status`
    still finds a job's last success within that window."""
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


def register_default_jobs() -> None:
    """Idempotent: safe to call from both the worker (which schedules
    `JOBS`) and the API (which only reads `JOBS` for `/api/v1/status`)."""
    if any(spec.name == "noop_heartbeat" for spec in JOBS):
        return
    register(JobSpec(name="noop_heartbeat", trigger=IntervalTrigger(seconds=30), handler=noop_heartbeat))
    register(
        JobSpec(name="ingest_runs_prune", trigger=CronTrigger(hour=21, minute=45), handler=ingest_runs_prune)
    )


async def main() -> None:
    configure_logging(json=get_settings().environment != "development")
    engine = get_app_writer_engine(pool_size=WORKER_APP_WRITER_POOL_SIZE, max_overflow=0)

    async with engine.connect() as conn:
        await cleanup_orphan_runs(conn)

    register_default_jobs()
    # Future agents: import their job module here so its top-level
    # `register(...)` call runs, e.g.:
    #   import stockticker.ingest.constituents  # noqa: F401

    await run_startup_chain(engine)

    scheduler = create_scheduler()
    for spec in JOBS:
        _schedule(scheduler, spec, engine)
    scheduler.start()
    _start_heartbeat_file_writer(scheduler)

    logger.info("worker.started", jobs=[spec.name for spec in JOBS])

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        await dispose_engines()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
