"""`bars_backfill` (system design §4; issue #4 review comment 1: the drift
and gap re-fetches reuse this same code path, never a separate one; issue
#4's third comment, from #5: a "gap" reason row is deleted once its
re-fetch commits, whether or not the provider had bars for those days).

One run works one batch of up to `BATCH_SIZE` symbols: first, every symbol
with an outstanding `refetch_requests` row -- one plan per symbol even if
it has more than one row (`resume_from` is the earliest of them,
`refetch_reasons` the union, so a symbol queued for both a drift rewrite
and a gap fill gets one pass that serves both, instead of the second plan
silently discarding the first's wider range). Any remaining room in the
batch is filled with Listings where `backfill_completed_at IS NULL`,
ordered by watermark (never-started symbols first, then whichever has
resumed least far) so a batch's members share a resume point and the
shared HTTP fetch doesn't over-request history most of the batch already
has. The batch is fetched as a whole -- one `BarSource.daily_bars` call --
from the *earliest* resume point any member needs, and
`plan_symbol_outcomes` (a pure function so it's unit-testable without HTTP
or a database) discards, per symbol, any row before that symbol's own
resume point.

`end` is now minus a 16-minute lag (system design §4), converted to its
New York trading date; a symbol whose new watermark reaches that date is
"caught up" and gets `backfill_completed_at` set. So does a symbol whose
fetch found nothing at all in its requested window (delisted before 2018,
never traded, or genuinely halted) -- otherwise a dead symbol would hold a
batch slot forever and starve the other ~500. `first_bar_date` is set
once, from the first run's own earliest row, via `COALESCE` -- a later
resume run's fetched window starts well after the real first bar, so it
must never overwrite an already-set value.

Every symbol commits on its own connection (system design §4: "Commit per
symbol"), opened only after `BarSource.daily_bars` has already returned --
no transaction is ever open across an HTTP call. A symbol with one or more
outstanding refetch rows has each of them resolved through issue #5's
shared `ingest.refetch` contract in the same per-symbol commit that
rewrites its series: `finish_refetch` on success (it leaves an open `gap`
row's attempt count alone -- no bar in the window on this pass -- and
counts that as a failed attempt itself), `mark_refetch_failed` for every
reason on a symbol that raises mid-write.

A bar whose `high`/`low` sits far outside its own `open`/`close` (a SIP bad
print, not a real move) is clamped before it's written -- see
`ingest.common.sanitize_bars`.

A `refetch_requests` row with `accepted_at IS NOT NULL` (`gap_check` has
given up on it after 3 attempts) is left alone -- `_select_batch` never
picks it up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.alpaca.bars import AlpacaBarSource
from stockticker.ingest.alpaca.client import require_alpaca_client
from stockticker.ingest.common import HISTORY_START, group_by_symbol, ny_date, sanitize_bars
from stockticker.ingest.job import FailedItem, JobContext, JobResult, JobSkipped
from stockticker.ingest.providers import BarSource, ProviderBar
from stockticker.ingest.refetch import RefetchReason, finish_refetch, mark_refetch_failed
from stockticker.ingest.sinks import upsert_bars

JOB_NAME = "bars_backfill"
BATCH_SIZE = 50
END_LAG = timedelta(minutes=16)


@dataclass(slots=True, frozen=True)
class SymbolBackfillPlan:
    symbol: str
    resume_from: date
    first_run: bool
    refetch_reasons: frozenset[RefetchReason] = frozenset()
    # The latest `requested_at` seen across this symbol's refetch rows at
    # selection time -- the per-reason delete only removes a row that was
    # already there when we read it, never one a fresh request inserted
    # concurrently while this batch was in flight.
    refetch_selected_at: datetime | None = None


@dataclass(slots=True)
class SymbolBackfillOutcome:
    symbol: str
    rows: list[ProviderBar] = field(default_factory=list)
    watermark: date | None = None
    first_bar_date: date | None = None
    completed: bool = False


def plan_symbol_outcomes(
    bars: list[ProviderBar],
    plans: list[SymbolBackfillPlan],
    end_trading_day: date,
) -> dict[str, SymbolBackfillOutcome]:
    """Group the batch's already-joined, sanitized bars per symbol, keep
    only a row at or after that symbol's own resume point (a batch call
    can return dates earlier than one symbol's resume point when another
    symbol in the same batch needed an earlier `start`), and compute the
    watermark and completion/first-bar-date bookkeeping. A symbol with no
    rows in its window is completed too -- nothing left to backfill."""
    by_symbol = group_by_symbol(bars)

    outcomes: dict[str, SymbolBackfillOutcome] = {}
    for plan in plans:
        rows = sorted(
            (bar for bar in by_symbol.get(plan.symbol, []) if bar.trade_date >= plan.resume_from),
            key=lambda bar: bar.trade_date,
        )
        watermark = rows[-1].trade_date if rows else None
        caught_up = bool(watermark and watermark >= end_trading_day)
        outcomes[plan.symbol] = SymbolBackfillOutcome(
            symbol=plan.symbol,
            rows=rows,
            watermark=watermark,
            first_bar_date=rows[0].trade_date if (rows and plan.first_run) else None,
            completed=caught_up or not rows,
        )
    return outcomes


async def bars_backfill(ctx: JobContext) -> JobResult:
    client = require_alpaca_client()
    return await run_bars_backfill(ctx.engine, AlpacaBarSource(client))


async def run_bars_backfill(engine: AsyncEngine, source: BarSource) -> JobResult:
    async with engine.connect() as conn:
        plans = await _select_batch(conn)
    if not plans:
        raise JobSkipped("no listings need backfilling")

    end = datetime.now(UTC) - END_LAG
    end_trading_day = ny_date(end)
    start = min(plan.resume_from for plan in plans)
    symbols = [plan.symbol for plan in plans]

    bars = await source.daily_bars(symbols, start, end.date())
    bars, sanity_failed = sanitize_bars(bars)
    outcomes = plan_symbol_outcomes(bars, plans, end_trading_day)

    rows_written = 0
    failed_items: list[FailedItem] = list(sanity_failed)
    for plan in plans:
        outcome = outcomes[plan.symbol]
        async with engine.connect() as conn:
            try:
                written = await _commit_symbol(conn, plan, outcome)
                rows_written += written
            except Exception as exc:  # noqa: BLE001 - recorded as a per-item failure, run continues
                await conn.rollback()
                failed_items.append(FailedItem(key=plan.symbol, error=str(exc)))
                for reason in plan.refetch_reasons:
                    await mark_refetch_failed(conn, plan.symbol, reason, str(exc))
                await conn.commit()

    return JobResult(rows_written=rows_written, failed_items=failed_items)


async def _select_batch(conn: AsyncConnection) -> list[SymbolBackfillPlan]:
    refetch_rows = (
        await conn.execute(
            text(
                "SELECT symbol, reason, from_date, requested_at FROM refetch_requests "
                "WHERE accepted_at IS NULL ORDER BY symbol"
            )
        )
    ).all()

    by_symbol: dict[str, tuple[date, set[RefetchReason], datetime]] = {}
    for row in refetch_rows:
        resume_from, reasons, selected_at = by_symbol.get(
            row.symbol, (row.from_date, set(), row.requested_at)
        )
        by_symbol[row.symbol] = (
            min(resume_from, row.from_date),
            reasons | {row.reason},
            max(selected_at, row.requested_at),
        )

    plans: list[SymbolBackfillPlan] = [
        SymbolBackfillPlan(
            symbol=symbol,
            resume_from=resume_from,
            first_run=False,
            refetch_reasons=frozenset(reasons),
            refetch_selected_at=selected_at,
        )
        for symbol, (resume_from, reasons, selected_at) in list(by_symbol.items())[:BATCH_SIZE]
    ]

    remaining = BATCH_SIZE - len(plans)
    if remaining > 0:
        already_picked = {plan.symbol for plan in plans}
        stmt = text(
            "SELECT l.symbol, w.value AS watermark FROM listings l "
            "LEFT JOIN ingest_watermarks w ON w.job = :job_name AND w.key = l.symbol "
            "WHERE l.is_active AND l.backfill_completed_at IS NULL AND l.symbol NOT IN :picked "
            "ORDER BY w.value NULLS FIRST, l.symbol LIMIT :limit"
        ).bindparams(bindparam("picked", expanding=True))
        incomplete = (
            await conn.execute(
                stmt, {"job_name": JOB_NAME, "picked": sorted(already_picked) or [""], "limit": remaining}
            )
        ).all()
        for row in incomplete:
            # "A resume starts from that date" (system design §4) -- the
            # watermark day itself, not the day after; re-writing it is a
            # harmless no-op through the idempotent upsert.
            resume_from = date.fromisoformat(row.watermark) if row.watermark else None
            plans.append(
                SymbolBackfillPlan(
                    symbol=row.symbol,
                    resume_from=resume_from or HISTORY_START,
                    first_run=resume_from is None,
                )
            )
    await conn.commit()
    return plans


async def _commit_symbol(
    conn: AsyncConnection, plan: SymbolBackfillPlan, outcome: SymbolBackfillOutcome
) -> int:
    written = 0
    if outcome.rows:
        result = await upsert_bars(conn, outcome.rows)
        written = result.rows_written
        if result.failed_items:
            # plan.symbol always comes from an existing listings row, so
            # upsert_bars's own "unknown symbol" check should never trigger
            # here -- surfaced as a real failure if it somehow does.
            symbols = ", ".join(item.key for item in result.failed_items)
            raise RuntimeError(f"unknown symbol(s) from upsert_bars: {symbols}")

    if outcome.watermark is not None:
        await conn.execute(
            text(
                "INSERT INTO ingest_watermarks (job, key, value, updated_at) "
                "VALUES (:job_name, :symbol, :value, now()) "
                "ON CONFLICT (job, key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at"
            ),
            {"job_name": JOB_NAME, "symbol": plan.symbol, "value": outcome.watermark.isoformat()},
        )

    if outcome.completed or outcome.first_bar_date is not None:
        await conn.execute(
            text(
                "UPDATE listings SET "
                "first_bar_date = COALESCE(first_bar_date, :first_bar_date), "
                "backfill_completed_at = CASE WHEN :completed THEN now() ELSE backfill_completed_at END, "
                "updated_at = now() "
                "WHERE symbol = :symbol"
            ),
            {"symbol": plan.symbol, "first_bar_date": outcome.first_bar_date, "completed": outcome.completed},
        )

    if plan.refetch_reasons:
        assert plan.refetch_selected_at is not None, "a plan with refetch reasons always has a selected_at"
        for reason in plan.refetch_reasons:
            await finish_refetch(conn, plan.symbol, reason, plan.refetch_selected_at)

    await conn.commit()
    return written


__all__ = [
    "BATCH_SIZE",
    "JOB_NAME",
    "SymbolBackfillOutcome",
    "SymbolBackfillPlan",
    "bars_backfill",
    "plan_symbol_outcomes",
    "run_bars_backfill",
]
