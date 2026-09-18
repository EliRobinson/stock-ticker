"""The job registry: one literal `JOBS` tuple, not a `register()` call plus
import side effects. A builder adding a job adds one `JobSpec` entry here
and nothing else -- `worker.py` schedules every entry, `/api/v1/status`
reports on every entry (even one that has never run), and `missing_keys` is
the union of `requires_keys` across all of them. No module needs importing
just to make its job exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from stockticker.config import RequiredKey
from stockticker.ingest.job import (
    ConfigMissingError,
    JobContext,
    JobFn,
    JobResult,
    JobSkipped,
    ingest_runs_prune,
)
from stockticker.timeutil import today_ny

# A laptop that slept through a cron firing still runs it once on wake;
# an interval job (polling) just catches the next tick instead.
CRON_MISFIRE_GRACE_SECONDS = 6 * 60 * 60
INTERVAL_MISFIRE_GRACE_SECONDS = 5


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

    def resolved_misfire_grace_time(self) -> int:
        if self.misfire_grace_time is not None:
            return self.misfire_grace_time
        return (
            CRON_MISFIRE_GRACE_SECONDS
            if isinstance(self.trigger, CronTrigger)
            else INTERVAL_MISFIRE_GRACE_SECONDS
        )


def resolve_handler(spec: JobSpec) -> JobFn:
    """Wrap `spec.handler` with the `requires_keys` and `trading_days_only`
    checks every job gets automatically -- job authors write only the
    handler body."""

    async def wrapped(ctx: JobContext) -> JobResult:
        missing = [key.value for key in spec.requires_keys if ctx.settings.is_missing(key)]
        if missing:
            raise ConfigMissingError(missing)
        if spec.trading_days_only:
            async with ctx.engine.connect() as conn:
                is_trading_day = await conn.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM trading_days WHERE trade_date = :d)"),
                    {"d": today_ny()},
                )
            if not is_trading_day:
                raise JobSkipped(f"{today_ny()} is not a Trading Day")
        return await spec.handler(ctx)

    return wrapped


# Builders: add one JobSpec here. Nothing else needs to change -- the
# scheduler, /api/v1/status, and missing_keys all read this tuple directly.
JOBS: tuple[JobSpec, ...] = (
    JobSpec(name="ingest_runs_prune", trigger=CronTrigger(hour=22, minute=0), handler=ingest_runs_prune),
)
