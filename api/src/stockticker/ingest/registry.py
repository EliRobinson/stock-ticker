"""The job registry: one literal `JOBS` tuple, not a `register()` call plus
import side effects. A builder adding a job adds one `JobSpec` entry here
and nothing else -- `worker.py` schedules every entry, `/api/v1/status`
reports on every entry (even one that has never run), and `missing_keys` is
the union of `requires_keys` across all of them. No module needs importing
just to make its job exist.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stockticker.config import RequiredKey
from stockticker.ingest.edgar.sync import edgar_sync
from stockticker.ingest.gap_check import gap_check
from stockticker.ingest.job import JobSpec
from stockticker.ingest.jobs.bars_backfill import bars_backfill
from stockticker.ingest.jobs.bars_daily import bars_daily
from stockticker.ingest.jobs.calendar_sync import calendar_sync
from stockticker.ingest.jobs.corporate_actions_sync import corporate_actions_sync
from stockticker.ingest.jobs.quotes_poll import quotes_poll
from stockticker.ingest.market_caps import market_caps_rebuild
from stockticker.ingest.retention import ingest_runs_prune
from stockticker.ingest.wikipedia.sync import constituents_sync

_ALPACA_KEYS = (RequiredKey.ALPACA_KEY_ID, RequiredKey.ALPACA_SECRET_KEY)

# Builders: add one JobSpec here. Nothing else needs to change -- the
# scheduler, /api/v1/status, and missing_keys all read this tuple directly.
JOBS: tuple[JobSpec, ...] = (
    JobSpec(name="ingest_runs_prune", trigger=CronTrigger(hour=22, minute=0), handler=ingest_runs_prune),
    JobSpec(name="constituents_sync", trigger=CronTrigger(hour=6, minute=0), handler=constituents_sync),
    JobSpec(
        name="edgar_sync",
        trigger=CronTrigger(day_of_week="sun", hour=7, minute=0),
        handler=edgar_sync,
        requires_keys=(RequiredKey.SEC_USER_AGENT,),
    ),
    JobSpec(
        name="market_caps_rebuild",
        trigger=CronTrigger(hour=21, minute=0),
        handler=market_caps_rebuild,
        runs_after=("bars_daily", "edgar_sync"),
    ),
    JobSpec(name="gap_check", trigger=CronTrigger(hour=21, minute=30), handler=gap_check),
    JobSpec(
        name="calendar_sync",
        trigger=CronTrigger(hour=6, minute=5),
        handler=calendar_sync,
        requires_keys=_ALPACA_KEYS,
    ),
    JobSpec(
        name="bars_backfill",
        trigger=IntervalTrigger(hours=1),
        handler=bars_backfill,
        requires_keys=_ALPACA_KEYS,
    ),
    JobSpec(
        name="bars_daily",
        trigger=CronTrigger(hour=16, minute=30),
        handler=bars_daily,
        trading_days_only=True,
        requires_keys=_ALPACA_KEYS,
    ),
    JobSpec(
        name="quotes_poll",
        trigger=IntervalTrigger(seconds=15),
        handler=quotes_poll,
        requires_keys=_ALPACA_KEYS,
        engine="quotes",
    ),
    JobSpec(
        name="corporate_actions_sync",
        trigger=CronTrigger(hour=6, minute=10),
        handler=corporate_actions_sync,
        requires_keys=_ALPACA_KEYS,
    ),
)
