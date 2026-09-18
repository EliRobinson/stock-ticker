"""The ingest worker process: an APScheduler `AsyncIOScheduler` running in
`America/New_York`, scheduling every `stockticker.ingest.registry.JOBS`
entry.

At startup, before the recurring schedule is registered: the heartbeat file
writer starts first (the compose healthcheck should never report unhealthy
just because the startup chain is still running), then `run_startup_chain`
runs `STARTUP_CHAIN` once, each step waiting for the previous one so the
first real ingest of the night has its inputs ready (`bars_backfill` needs
Listings from `constituents_sync`; `market_caps_rebuild` needs bars,
shares, *and* `corporate_actions_sync`'s splits -- without splits synced
first, `market_caps_rebuild` refuses to write a Company at all, so the
first-ever rebuild would write nothing). `run_job` never raises, so a failed step doesn't abort the
chain -- the next step runs regardless, and if ITS inputs are empty because
the step before it failed, its own handler records `skipped` for the
honest reason. A step naming a job not yet in `JOBS` (the ingest agents add
theirs later) is skipped with a log line, not an error.
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.config import get_settings
from stockticker.db import dispose_engines, get_quotes_engine, get_worker_app_writer_engine
from stockticker.ingest.job import JobSpec, cleanup_orphan_runs_at_startup, run_job
from stockticker.ingest.registry import JOBS
from stockticker.logging import configure_logging, get_logger
from stockticker.timeutil import NY_TZ

logger = get_logger(__name__)

SCHEDULER_TIMEZONE = NY_TZ
JOB_DEFAULTS = {"coalesce": True, "misfire_grace_time": 5}

# Worker liveness for the compose healthcheck: touched every 15s, stale
# past 60s. Not an ingest_runs job -- pure process liveness.
HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 15

# Job names other agents' modules register in ingest/registry.py's JOBS
# tuple (issue #4 and friends). A step whose job isn't registered yet is
# skipped, not an error -- see run_startup_chain. Each element is a tuple
# of names run concurrently, even the single-job steps, so the type stays
# uniform.
STARTUP_CHAIN: tuple[tuple[str, ...], ...] = (
    ("constituents_sync",),
    ("calendar_sync",),
    ("bars_backfill", "edgar_sync", "corporate_actions_sync"),
    ("market_caps_rebuild",),
)


async def run_startup_chain(engine: AsyncEngine, quotes_engine: AsyncEngine) -> None:
    by_name = {spec.name: spec for spec in JOBS}
    for names in STARTUP_CHAIN:
        for name in names:
            if name not in by_name:
                logger.debug("startup_chain.step_not_registered", job=name)
        specs = [by_name[name] for name in names if name in by_name]
        if not specs:
            continue
        logger.info("startup_chain.step", jobs=[spec.name for spec in specs])
        # run_job never raises on its own, but return_exceptions=True is
        # cheap insurance against a bug in run_job itself still not
        # aborting every other step in this gather.
        await asyncio.gather(
            *(_run_startup_job(spec, engine, quotes_engine) for spec in specs),
            return_exceptions=True,
        )


async def _run_startup_job(spec: JobSpec, engine: AsyncEngine, quotes_engine: AsyncEngine) -> None:
    """Run one startup-chain job. `bars_backfill` loops until it reports
    nothing left to do (issue #38: a first boot otherwise takes ~10 hours
    at 50 symbols per hourly cron tick). Other jobs run once."""
    while True:
        outcome = await run_job(spec, engine=engine, quotes_engine=quotes_engine)
        if spec.name != "bars_backfill":
            return
        # succeeded / partial: another batch may remain. skipped: caught up.
        # failed / skipped_locked: stop — don't spin on a hard error or a lock.
        if outcome.status in ("skipped", "skipped_locked", "failed"):
            return


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE, job_defaults=JOB_DEFAULTS)


def _schedule(
    scheduler: AsyncIOScheduler, spec: JobSpec, engine: AsyncEngine, quotes_engine: AsyncEngine
) -> None:
    # Jobs that declare runs_after=(..., spec.name, ...) run immediately
    # after this one's own scheduled trigger fires, every time -- not only
    # at startup. E.g. market_caps_rebuild follows both bars_daily and
    # edgar_sync (system design §4); each trigger runs it again.
    followers = [other for other in JOBS if spec.name in other.runs_after]

    async def _runner() -> None:
        await run_job(spec, engine=engine, quotes_engine=quotes_engine)
        for follower in followers:
            await run_job(follower, engine=engine, quotes_engine=quotes_engine)

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
        "interval",
        seconds=HEARTBEAT_INTERVAL_SECONDS,
        id="_heartbeat_file",
        replace_existing=True,
    )


async def main() -> None:
    configure_logging(json=get_settings().environment != "development")
    engine = get_worker_app_writer_engine()
    quotes_engine = get_quotes_engine()

    await cleanup_orphan_runs_at_startup(engine, [spec.name for spec in JOBS])

    scheduler = create_scheduler()
    scheduler.start()
    _start_heartbeat_file_writer(scheduler)
    logger.info("worker.heartbeat_started")

    await run_startup_chain(engine, quotes_engine)

    for spec in JOBS:
        _schedule(scheduler, spec, engine, quotes_engine)
    logger.info("worker.started", jobs=[spec.name for spec in JOBS])

    stop_event = asyncio.Event()
    # `docker compose stop`/`down` send SIGTERM. asyncio installs no
    # handler for it by default, so without this the process is killed
    # outright -- the `finally` below (and its pool disposal) never runs,
    # and every pooled connection ends as an abrupt disconnect instead of
    # a clean close.
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop_event.set)
    try:
        await stop_event.wait()
        logger.info("worker.shutdown_requested")
    finally:
        scheduler.shutdown(wait=False)
        await dispose_engines()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
