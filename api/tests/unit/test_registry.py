from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stockticker.ingest.job import (
    CRON_MISFIRE_GRACE_SECONDS,
    INTERVAL_MISFIRE_GRACE_SECONDS,
    JobResult,
    JobSpec,
)
from stockticker.ingest.registry import JOBS


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


def test_registry_defines_no_functions_or_classes_of_its_own() -> None:
    # registry.py's whole job is `JOBS: tuple[JobSpec, ...]` -- JobSpec
    # itself lives in job.py, and every handler and trigger/key type it
    # references is imported from elsewhere (e.g. ingest/retention.py for
    # ingest_runs_prune). This checks that shape without pinning down
    # *which* names it imports -- a fixed allowlist broke the moment
    # another builder registered their own job, which needs its own
    # handler (and possibly RequiredKey/trigger) imports.
    import inspect

    import stockticker.ingest.registry as registry_module

    for name, value in vars(registry_module).items():
        if name.startswith("_") or name == "JOBS":
            continue
        if inspect.isfunction(value) or inspect.isclass(value):
            assert getattr(value, "__module__", None) != registry_module.__name__, (
                f"registry.{name} is defined in registry.py itself -- registry.py should only "
                "import and assemble JOBS, never define a handler or type of its own."
            )
