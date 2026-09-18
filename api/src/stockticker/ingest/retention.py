"""`ingest_runs` retention (system design §4): `succeeded`, `skipped_locked`,
and `skipped` rows are noise past a week; `failed`/`partial` rows are kept
longer since they're worth investigating. Not in `ingest/job.py` (the
wrapper) -- this is an ordinary job like any other, registered in
`ingest/registry.py`."""

from __future__ import annotations

from sqlalchemy import text

from stockticker.ingest.job import JobContext, JobResult


async def ingest_runs_prune(ctx: JobContext) -> JobResult:
    async with ctx.engine.connect() as conn:
        recent = await conn.execute(
            text(
                "DELETE FROM ingest_runs WHERE status IN ('succeeded', 'skipped_locked', 'skipped') "
                "AND started_at < now() - interval '7 days'"
            )
        )
        old_failures = await conn.execute(
            text(
                "DELETE FROM ingest_runs WHERE status IN ('failed', 'partial') "
                "AND started_at < now() - interval '90 days'"
            )
        )
        await conn.commit()
    return JobResult(rows_written=(recent.rowcount or 0) + (old_failures.rowcount or 0))
