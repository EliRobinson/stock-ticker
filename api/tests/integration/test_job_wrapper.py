"""Job wrapper tests (system design §4) against a real, migrated Postgres.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.job import (
    ConfigMissingError,
    FailedItem,
    JobResult,
    JobSkipped,
    cleanup_orphan_runs,
    run_job,
)


def _job_name() -> str:
    return f"test_job_{uuid.uuid4().hex[:10]}"


async def _runs_for(engine: AsyncEngine, job_name: str) -> list[Row[Any]]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT status, rows_written, items_failed, error FROM ingest_runs "
                "WHERE job = :job ORDER BY id"
            ),
            {"job": job_name},
        )
        return list(result.all())


async def _cleanup(engine: AsyncEngine, job_name: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("DELETE FROM ingest_runs WHERE job = :job"), {"job": job_name})
        await conn.commit()


async def test_run_job_succeeds_and_records_the_run(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(conn: object) -> JobResult:
        return JobResult(rows_written=3)

    try:
        result = await run_job(job_name, fn, engine=app_writer_engine)
        assert result is not None
        assert result.rows_written == 3

        rows = await _runs_for(app_writer_engine, job_name)
        assert len(rows) == 1
        assert rows[0].status == "succeeded"
        assert rows[0].items_failed == 0
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_is_partial_when_items_failed(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(conn: object) -> JobResult:
        return JobResult(rows_written=1, failed_items=[FailedItem(key="AAPL", error="boom")])

    try:
        result = await run_job(job_name, fn, engine=app_writer_engine)
        assert result is not None
        assert len(result.failed_items) == 1

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "partial"
        assert rows[0].items_failed == 1
        assert rows[0].error["items"][0] == {"key": "AAPL", "error": "boom"}
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_is_failed_on_uncaught_exception(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(conn: object) -> JobResult:
        raise RuntimeError("kaboom")

    try:
        with pytest.raises(RuntimeError, match="kaboom"):
            await run_job(job_name, fn, engine=app_writer_engine)

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
        assert rows[0].error["message"] == "kaboom"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_skips_when_another_process_holds_the_lock(
    app_writer_engine: AsyncEngine,
) -> None:
    job_name = _job_name()

    # app_writer only has EXECUTE on pg_try_advisory_lock/pg_advisory_unlock
    # (the plain, blocking pg_advisory_lock was never granted -- run_job
    # never calls it), so the "another process holds it" setup uses the try
    # variant too; it still holds the lock until unlocked.
    holder = await app_writer_engine.connect()
    still_locked = await holder.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
    await holder.commit()
    assert still_locked is True

    called = False

    async def fn(conn: object) -> JobResult:
        nonlocal called
        called = True
        return JobResult()

    try:
        result = await run_job(job_name, fn, engine=app_writer_engine)
        assert result is None
        assert called is False

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "skipped_locked"
    finally:
        await holder.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
        await holder.commit()
        await holder.close()
        await _cleanup(app_writer_engine, job_name)


async def test_cleanup_orphan_runs_marks_stale_running_rows_failed(
    app_writer_engine: AsyncEngine,
) -> None:
    job_name = _job_name()
    try:
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ingest_runs (job, status, started_at) VALUES (:job, 'running', :started_at)"
                ),
                {"job": job_name, "started_at": datetime.now(UTC) - timedelta(hours=2)},
            )
            await conn.commit()

            count = await cleanup_orphan_runs(conn)
            assert count >= 1

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_cleanup_orphan_runs_leaves_recent_running_rows_alone(
    app_writer_engine: AsyncEngine,
) -> None:
    job_name = _job_name()
    try:
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ingest_runs (job, status, started_at) VALUES (:job, 'running', :started_at)"
                ),
                {"job": job_name, "started_at": datetime.now(UTC)},
            )
            await conn.commit()

            await cleanup_orphan_runs(conn)

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "running"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_records_config_missing(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(conn: object) -> JobResult:
        raise ConfigMissingError(["ALPACA_KEY_ID"])

    try:
        result = await run_job(job_name, fn, engine=app_writer_engine)
        assert result == JobResult()

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
        assert rows[0].error["type"] == "config_missing"
        assert rows[0].error["missing_keys"] == ["ALPACA_KEY_ID"]
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_records_skipped(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(conn: object) -> JobResult:
        raise JobSkipped("no listings yet")

    try:
        result = await run_job(job_name, fn, engine=app_writer_engine)
        assert result == JobResult()

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "skipped"
        assert rows[0].error["message"] == "no listings yet"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_fails_a_stale_running_row_at_any_age(app_writer_engine: AsyncEngine) -> None:
    """The per-trigger orphan check (not just the 1h `cleanup_orphan_runs`
    backstop) marks a leftover `running` row failed the moment the job is
    next attempted, however recent it is."""
    job_name = _job_name()
    try:
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ingest_runs (job, status, started_at) "
                    "VALUES (:job, 'running', now() - interval '5 seconds')"
                ),
                {"job": job_name},
            )
            await conn.commit()

        async def fn(conn: object) -> JobResult:
            return JobResult(rows_written=1)

        await run_job(job_name, fn, engine=app_writer_engine)

        rows = await _runs_for(app_writer_engine, job_name)
        assert len(rows) == 2
        orphaned, succeeded = rows
        assert orphaned.status == "failed"
        assert orphaned.error["type"] == "orphaned"
        assert succeeded.status == "succeeded"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_skipped_locked_run_queues_a_rerun_the_holder_honors(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    holder = await app_writer_engine.connect()
    still_locked = await holder.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
    await holder.commit()
    assert still_locked is True

    async def never_called(conn: object) -> JobResult:
        raise AssertionError("fn must not run while the lock is held")

    try:
        # A second attempt while the lock is held: skipped_locked, and it
        # should leave a rerun_requested watermark for the holder.
        skipped = await run_job(job_name, never_called, engine=app_writer_engine)
        assert skipped is None

        async with app_writer_engine.connect() as conn:
            watermark = (
                await conn.execute(
                    text("SELECT value FROM ingest_watermarks WHERE job = :job AND key = 'rerun_requested'"),
                    {"job": job_name},
                )
            ).first()
            assert watermark is not None

    finally:
        await holder.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
        await holder.commit()
        await holder.close()

    call_count = 0

    async def counting_fn(conn: object) -> JobResult:
        nonlocal call_count
        call_count += 1
        return JobResult(rows_written=call_count)

    try:
        # This is the next run_job call to acquire the lock for this job.
        # Finding the rerun_requested watermark left by the skipped_locked
        # attempt above, it should run counting_fn twice: once for itself,
        # once more to honor the queued rerun.
        result = await run_job(job_name, counting_fn, engine=app_writer_engine)
        assert result is not None
        assert call_count == 2

        rows = await _runs_for(app_writer_engine, job_name)
        assert len(rows) == 3  # skipped_locked, then two succeeded runs
        assert [row.status for row in rows] == ["skipped_locked", "succeeded", "succeeded"]

        async with app_writer_engine.connect() as conn:
            watermark = (
                await conn.execute(
                    text("SELECT value FROM ingest_watermarks WHERE job = :job AND key = 'rerun_requested'"),
                    {"job": job_name},
                )
            ).first()
            assert watermark is None  # cleared once honored
    finally:
        await _cleanup(app_writer_engine, job_name)
