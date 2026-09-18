"""Job wrapper tests (system design §4) against a real, migrated Postgres.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ingest.job import (
    ConfigMissingError,
    FailedItem,
    JobContext,
    JobResult,
    JobSkipped,
    cleanup_orphan_runs_at_startup,
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
        await conn.execute(text("DELETE FROM ingest_watermarks WHERE job = :job"), {"job": job_name})
        await conn.commit()


async def test_run_job_succeeds_and_records_the_run(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(ctx: JobContext) -> JobResult:
        assert ctx.run_id > 0
        assert ctx.settings is not None
        return JobResult(rows_written=3)

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)
        assert outcome.status == "succeeded"
        assert outcome.result is not None
        assert outcome.result.rows_written == 3

        rows = await _runs_for(app_writer_engine, job_name)
        assert len(rows) == 1
        assert rows[0].status == "succeeded"
        assert rows[0].items_failed == 0
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_is_partial_when_items_failed(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(ctx: JobContext) -> JobResult:
        return JobResult(rows_written=1, failed_items=[FailedItem(key="AAPL", error="boom")])

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)
        assert outcome.status == "partial"
        assert outcome.result is not None
        assert len(outcome.result.failed_items) == 1

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "partial"
        assert rows[0].items_failed == 1
        assert rows[0].error["items"][0] == {"key": "AAPL", "error": "boom"}
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_is_failed_on_uncaught_exception_and_never_raises(
    app_writer_engine: AsyncEngine,
) -> None:
    job_name = _job_name()

    async def fn(ctx: JobContext) -> JobResult:
        raise RuntimeError("kaboom")

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)  # must not raise
        assert outcome.status == "failed"
        assert outcome.error is not None
        assert outcome.error["message"] == "kaboom"

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
        assert rows[0].error["message"] == "kaboom"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_records_config_missing(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(ctx: JobContext) -> JobResult:
        raise ConfigMissingError(["ALPACA_KEY_ID"])

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)
        assert outcome.status == "failed"
        assert outcome.error is not None
        assert outcome.error["type"] == "config_missing"
        assert outcome.error["missing_keys"] == ["ALPACA_KEY_ID"]

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
        assert rows[0].error["type"] == "config_missing"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_records_skipped(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    async def fn(ctx: JobContext) -> JobResult:
        raise JobSkipped("no listings yet")

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)
        assert outcome.status == "skipped"

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "skipped"
        assert rows[0].error["message"] == "no listings yet"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_skips_when_another_process_holds_the_lock(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    holder = await app_writer_engine.connect()
    still_locked = await holder.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
    await holder.commit()
    assert still_locked is True

    called = False

    async def fn(ctx: JobContext) -> JobResult:
        nonlocal called
        called = True
        return JobResult()

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)
        assert outcome.status == "skipped_locked"
        assert called is False

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "skipped_locked"
    finally:
        await holder.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
        await holder.commit()
        await holder.close()
        await _cleanup(app_writer_engine, job_name)


async def test_run_job_fails_a_stale_running_row_at_any_age(app_writer_engine: AsyncEngine) -> None:
    """The per-trigger orphan check (not just the startup sweep) marks a
    leftover `running` row failed the moment the job is next attempted,
    however recent it is."""
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

        async def fn(ctx: JobContext) -> JobResult:
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


async def test_cleanup_orphan_runs_at_startup_fails_rows_it_can_lock(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()
    try:
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text("INSERT INTO ingest_runs (job, status, started_at) VALUES (:job, 'running', now())"),
                {"job": job_name},
            )
            await conn.commit()

        count = await cleanup_orphan_runs_at_startup(app_writer_engine, [job_name])
        assert count == 1

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_cleanup_orphan_runs_at_startup_skips_a_job_someone_else_holds(
    app_writer_engine: AsyncEngine,
) -> None:
    job_name = _job_name()
    holder = await app_writer_engine.connect()
    await holder.execute(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
    await holder.commit()
    try:
        async with app_writer_engine.connect() as conn:
            await conn.execute(
                text("INSERT INTO ingest_runs (job, status, started_at) VALUES (:job, 'running', now())"),
                {"job": job_name},
            )
            await conn.commit()

        count = await cleanup_orphan_runs_at_startup(app_writer_engine, [job_name])
        assert count == 0

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "running"
    finally:
        await holder.execute(text("SELECT pg_advisory_unlock(hashtext(:job))"), {"job": job_name})
        await holder.commit()
        await holder.close()
        await _cleanup(app_writer_engine, job_name)


async def test_skipped_locked_run_queues_a_rerun_the_holder_honors(app_writer_engine: AsyncEngine) -> None:
    job_name = _job_name()

    holder = await app_writer_engine.connect()
    still_locked = await holder.scalar(text("SELECT pg_try_advisory_lock(hashtext(:job))"), {"job": job_name})
    await holder.commit()
    assert still_locked is True

    async def never_called(ctx: JobContext) -> JobResult:
        raise AssertionError("fn must not run while the lock is held")

    try:
        skipped = await run_job(job_name, never_called, engine=app_writer_engine)
        assert skipped.status == "skipped_locked"

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

    async def counting_fn(ctx: JobContext) -> JobResult:
        nonlocal call_count
        call_count += 1
        return JobResult(rows_written=call_count)

    try:
        # This is the next run_job call to acquire the lock for this job.
        # Finding the rerun_requested watermark left by the skipped_locked
        # attempt above, it should run counting_fn twice: once for itself,
        # once more to honor the queued rerun.
        outcome = await run_job(job_name, counting_fn, engine=app_writer_engine)
        assert outcome.status == "succeeded"
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


async def test_run_job_detects_a_terminated_lock_connection(app_writer_engine: AsyncEngine) -> None:
    """Kills the backend holding the advisory lock mid-run with
    `pg_terminate_backend`, proving the liveness check catches asyncpg's
    `InterfaceError`/`ConnectionDoesNotExistError` -- not `OperationalError`,
    which SQLAlchemy's asyncpg dialect never raises for these."""
    job_name = _job_name()

    async def fn(ctx: JobContext) -> JobResult:
        async with ctx.engine.connect() as conn:
            pid = await conn.scalar(text("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted"))
            assert pid is not None, "expected the lock connection to hold a granted advisory lock"
            await conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            await conn.commit()
        return JobResult(rows_written=1)

    try:
        outcome = await run_job(job_name, fn, engine=app_writer_engine)
        assert outcome.status == "failed"
        assert outcome.error is not None
        assert outcome.error["type"] == "lock_connection_lost"

        rows = await _runs_for(app_writer_engine, job_name)
        assert rows[0].status == "failed"
        assert rows[0].error["type"] == "lock_connection_lost"
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_concurrent_attempts_are_all_served_with_no_stranded_rerun(
    app_writer_engine: AsyncEngine,
) -> None:
    """Several run_job calls for the same job, fired concurrently: exactly
    one holds the lock at a time, but nothing raises, no attempt is
    silently dropped, and no rerun_requested watermark is left dangling
    once everything settles -- the property the requester-sets-flag-then-
    tries-the-lock race (system design §4) exists to protect."""
    job_name = _job_name()
    run_count = 0
    count_lock = asyncio.Lock()

    async def fn(ctx: JobContext) -> JobResult:
        nonlocal run_count
        async with count_lock:
            run_count += 1
        await asyncio.sleep(0.2)
        return JobResult(rows_written=1)

    try:
        outcomes = await asyncio.gather(*(run_job(job_name, fn, engine=app_writer_engine) for _ in range(4)))

        assert all(o.status in ("succeeded", "skipped_locked") for o in outcomes)
        assert run_count >= 1

        async with app_writer_engine.connect() as conn:
            watermark = (
                await conn.execute(
                    text("SELECT 1 FROM ingest_watermarks WHERE job = :job AND key = 'rerun_requested'"),
                    {"job": job_name},
                )
            ).first()
        assert watermark is None
    finally:
        await _cleanup(app_writer_engine, job_name)


async def test_cleanup_orphan_runs_at_startup_is_a_no_op_with_no_stale_rows(
    app_writer_engine: AsyncEngine,
) -> None:
    count = await cleanup_orphan_runs_at_startup(app_writer_engine, [f"nonexistent_{uuid.uuid4().hex[:8]}"])
    assert count == 0
