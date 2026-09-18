from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from stockticker.config import RequiredKey
from stockticker.ingest.job import JobSpec
from stockticker.ingest.registry import JOBS
from stockticker.worker import STARTUP_CHAIN


def _specs() -> dict[str, JobSpec]:
    return {spec.name: spec for spec in JOBS}


def _cron_fields(trigger: object) -> dict[str, str]:
    assert isinstance(trigger, CronTrigger)
    return {field.name: str(field) for field in trigger.fields}


def test_reference_jobs_are_registered_on_the_section_4_schedules() -> None:
    specs = _specs()

    constituents = _cron_fields(specs["constituents_sync"].trigger)
    assert (constituents["hour"], constituents["minute"]) == ("6", "0")

    edgar = _cron_fields(specs["edgar_sync"].trigger)
    assert (edgar["day_of_week"], edgar["hour"], edgar["minute"]) == ("sun", "7", "0")
    assert specs["edgar_sync"].requires_keys == (RequiredKey.SEC_USER_AGENT,)

    rebuild = _cron_fields(specs["market_caps_rebuild"].trigger)
    assert (rebuild["hour"], rebuild["minute"]) == ("21", "0")

    gaps = _cron_fields(specs["gap_check"].trigger)
    assert (gaps["hour"], gaps["minute"]) == ("21", "30")


def test_market_caps_rebuild_follows_bars_daily_and_edgar_sync() -> None:
    assert _specs()["market_caps_rebuild"].runs_after == ("bars_daily", "edgar_sync")


def test_startup_chain_steps_owned_here_are_registered() -> None:
    chain = {name for step in STARTUP_CHAIN for name in ((step,) if isinstance(step, str) else step)}

    assert {"constituents_sync", "edgar_sync", "market_caps_rebuild"} <= chain & set(_specs())


def test_job_names_are_unique() -> None:
    names = [spec.name for spec in JOBS]

    assert len(names) == len(set(names))
