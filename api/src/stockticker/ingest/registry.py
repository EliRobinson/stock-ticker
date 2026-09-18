"""The job registry: one literal `JOBS` tuple, not a `register()` call plus
import side effects. A builder adding a job adds one `JobSpec` entry here
and nothing else -- `worker.py` schedules every entry, `/api/v1/status`
reports on every entry (even one that has never run), and `missing_keys` is
the union of `requires_keys` across all of them. No module needs importing
just to make its job exist.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from stockticker.ingest.job import JobSpec
from stockticker.ingest.retention import ingest_runs_prune

# Builders: add one JobSpec here. Nothing else needs to change -- the
# scheduler, /api/v1/status, and missing_keys all read this tuple directly.
JOBS: tuple[JobSpec, ...] = (
    JobSpec(name="ingest_runs_prune", trigger=CronTrigger(hour=22, minute=0), handler=ingest_runs_prune),
)
