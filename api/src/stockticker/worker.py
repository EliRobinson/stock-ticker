"""The ingest worker process: an APScheduler `AsyncIOScheduler` running in
`America/New_York`, scheduling every `stockticker.ingest.registry.JOBS`
entry.

At startup, before the recurring schedule is registered: the heartbeat file
writer starts first (the compose healthcheck should never report unhealthy
just because the startup chain is still running), then `run_startup_chain`
runs `STARTUP_CHAIN` once, each step waiting for the previous one so the
first real ingest of the night has its inputs ready (`bars_backfill` needs
Listings from `constituents_sync`, `market_caps_rebuild` needs both bars
and shares). `run_job` never raises, so a failed step doesn't abort the
chain -- the next step runs regardless, and if ITS inputs are empty because
the step before it failed, its own handler records `skipped` for the
honest reason. A step naming a job not yet in `JOBS` (the ingest agents add
theirs later) is skipped with a log line, not an error.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.config import get_settings
from stockticker.db import dispose_engines, get_app_writer_engine, get_quotes_engine
from stockticker.ingest.job import cleanup_orphan_runs_at_startup, run_job
from stockticker.ingest.registry import JOBS, JobSpec, resolve_handler
from stockticker.logging import configure_logging, get_logger
from stockticker.timeutil import NY_TZ

logger = get_logger(__name__)

SCHEDULER_TIMEZONE = NY_TZ
JOB_DEFAULTS = {"coalesce": True, "misfire_grace_time": 5}

# Worker liveness for the compose healthcheck: touched every 15s, stale
# past 60s. Not an ingest_runs job -- pure process liveness.
HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 15

WORKER_APP_WRITER_POOL_SIZE = 6

# Job names other agents' modules register in ingest/registry.py's JOBS
# tuple (issue #4 and friends). A step whose job isn't registered yet is
# skipped, not an error -- see run_startup_chain.
STARTUP_CHAIN: list[str | tuple[str, ...]] = [
    "constituents_sync",
    "calendar_sync",
    ("bars_backfill", "edgar_sync"),
    "market_caps_rebuild",
]


async def run_startup_chain(engine: AsyncEngine, quotes_engine: AsyncEngine) -> None:
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
        # run_job never raises, so gather needs no return_exceptions=True --
        # every step runs regardless of what the previous one did.
        await asyncio.gather(
            *(
                run_job(spec.name, resolve_handler(spec), engine=engine, quotes_engine=quotes_engine)
                for spec in specs
            )
        )


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE, job_defaults=JOB_DEFAULTS)


def _schedule(
    scheduler: AsyncIOScheduler, spec: JobSpec, engine: AsyncEngine, quotes_engine: AsyncEngine
) -> None:
    wrapped = resolve_handler(spec)

    async def _runner() -> None:
        await run_job(spec.name, wrapped, engine=engine, quotes_engine=quotes_engine)

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
    engine = get_app_writer_engine(pool_size=WORKER_APP_WRITER_POOL_SIZE, max_overflow=0)
    quotes_engine = get_quotes_engine()

    await cleanup_orphan_runs_at_startup(engine, (spec.name for spec in JOBS))

    scheduler = create_scheduler()
    scheduler.start()
    _start_heartbeat_file_writer(scheduler)
    logger.info("worker.heartbeat_started")

    await run_startup_chain(engine, quotes_engine)

    for spec in JOBS:
        _schedule(scheduler, spec, engine, quotes_engine)
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
