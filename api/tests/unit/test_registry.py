from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stockticker.ingest.job import JobResult
from stockticker.ingest.registry import (
    CRON_MISFIRE_GRACE_SECONDS,
    INTERVAL_MISFIRE_GRACE_SECONDS,
    JOBS,
    JobSpec,
)


async def _noop(ctx: object) -> JobResult:  # pragma: no cover - never called
    raise AssertionError


def test_cron_jobs_default_to_six_hour_misfire_grace() -> None:
    spec = JobSpec(name="nightly", trigger=CronTrigger(hour=21), handler=_noop)
    assert spec.resolved_misfire_grace_time() == CRON_MISFIRE_GRACE_SECONDS
    assert CRON_MISFIRE_GRACE_SECONDS == 6 * 60 * 60


def test_interval_jobs_default_to_five_second_misfire_grace() -> None:
    spec = JobSpec(name="poll", trigger=IntervalTrigger(seconds=15), handler=_noop)
    assert spec.resolved_misfire_grace_time() == INTERVAL_MISFIRE_GRACE_SECONDS
    assert INTERVAL_MISFIRE_GRACE_SECONDS == 5


def test_explicit_misfire_grace_time_wins() -> None:
    spec = JobSpec(
        name="custom",
        trigger=IntervalTrigger(seconds=15),
        handler=_noop,
        misfire_grace_time=42,
    )
    assert spec.resolved_misfire_grace_time() == 42


def test_jobs_tuple_has_no_duplicate_names() -> None:
    names = [spec.name for spec in JOBS]
    assert len(names) == len(set(names))


def test_noop_heartbeat_was_removed() -> None:
    assert "noop_heartbeat" not in {spec.name for spec in JOBS}
