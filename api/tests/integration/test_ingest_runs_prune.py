"""`ingest_runs_prune` retention (reliability review) against a real,
migrated Postgres. See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.config import get_settings
from stockticker.ingest.job import JobContext, ingest_runs_prune
from stockticker.logging import get_logger


async def _insert_run(engine: AsyncEngine, job: str, status: str, age: timedelta) -> None:
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO ingest_runs (job, status, started_at, finished_at) "
                "VALUES (:job, :status, :started_at, :started_at)"
            ),
            {"job": job, "status": status, "started_at": datetime.now(UTC) - age},
        )
        await conn.commit()


async def _status_for(engine: AsyncEngine, job: str) -> str | None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT status FROM ingest_runs WHERE job = :job"), {"job": job})
        ).first()
        return row.status if row else None


async def test_ingest_runs_prune_removes_old_succeeded_and_keeps_recent(
    app_writer_engine: AsyncEngine,
) -> None:
    old_success = f"test_job_{uuid.uuid4().hex[:10]}"
    recent_success = f"test_job_{uuid.uuid4().hex[:10]}"
    old_failure_kept = f"test_job_{uuid.uuid4().hex[:10]}"
    very_old_failure = f"test_job_{uuid.uuid4().hex[:10]}"

    try:
        await _insert_run(app_writer_engine, old_success, "succeeded", timedelta(days=8))
        await _insert_run(app_writer_engine, recent_success, "succeeded", timedelta(days=1))
        await _insert_run(app_writer_engine, old_failure_kept, "failed", timedelta(days=8))
        await _insert_run(app_writer_engine, very_old_failure, "failed", timedelta(days=91))

        ctx = JobContext(
            engine=app_writer_engine, run_id=0, settings=get_settings(), log=get_logger(__name__)
        )
        await ingest_runs_prune(ctx)

        assert await _status_for(app_writer_engine, old_success) is None
        assert await _status_for(app_writer_engine, recent_success) == "succeeded"
        assert await _status_for(app_writer_engine, old_failure_kept) == "failed"
        assert await _status_for(app_writer_engine, very_old_failure) is None
    finally:
        async with app_writer_engine.connect() as conn:
            for job in (old_success, recent_success, old_failure_kept, very_old_failure):
                await conn.execute(text("DELETE FROM ingest_runs WHERE job = :job"), {"job": job})
            await conn.commit()
