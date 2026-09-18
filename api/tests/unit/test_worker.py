from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stockticker.worker import (
    CRON_MISFIRE_GRACE_SECONDS,
    INTERVAL_MISFIRE_GRACE_SECONDS,
    JobSpec,
)


async def _noop(conn: object) -> None:  # pragma: no cover - never called
    raise AssertionError


def test_cron_jobs_default_to_six_hour_misfire_grace() -> None:
    spec = JobSpec(name="nightly", trigger=CronTrigger(hour=21), handler=_noop)  # type: ignore[arg-type]
    assert spec.resolved_misfire_grace_time() == CRON_MISFIRE_GRACE_SECONDS
    assert CRON_MISFIRE_GRACE_SECONDS == 6 * 60 * 60


def test_interval_jobs_default_to_five_second_misfire_grace() -> None:
    spec = JobSpec(name="poll", trigger=IntervalTrigger(seconds=15), handler=_noop)  # type: ignore[arg-type]
    assert spec.resolved_misfire_grace_time() == INTERVAL_MISFIRE_GRACE_SECONDS
    assert INTERVAL_MISFIRE_GRACE_SECONDS == 5


def test_explicit_misfire_grace_time_wins() -> None:
    spec = JobSpec(
        name="custom",
        trigger=IntervalTrigger(seconds=15),
        handler=_noop,  # type: ignore[arg-type]
        misfire_grace_time=42,
    )
    assert spec.resolved_misfire_grace_time() == 42
