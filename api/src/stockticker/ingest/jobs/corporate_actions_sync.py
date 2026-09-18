"""`corporate_actions_sync` (system design §4): Alpaca `/v1/corporate-actions`,
batched by symbol, for forward/reverse splits, cash dividends, and name
changes. Every symbol looks back `LOOKBACK_DAYS`; a symbol's *own* very
first run (no `bootstrapped:{symbol}` watermark yet) reaches back to
2018-01-01 instead, since the free tier's short lookback would otherwise
miss history -- one watermark per symbol, written only after that symbol's
batch commits, so a Company added to the index later still gets its own
full look-back (issue #4's third comment, from #5). `event_date` is
`ex_date` for splits and dividends, `process_date` for name changes; a name
change is linked to the Company through its *old* Listing's `cik`, looked
up across *every* Listing (including inactive ones -- the old Listing is
usually already inactive by the time the rename itself lands). Every write
is idempotent on `events (source, source_ref)`, keyed off Alpaca's own
announcement `id`.

`to_event` is a pure function (one action in, one `EventRow` or
`FailedItem` out) so a single malformed action never takes the rest of a
batch down with it -- `AlpacaClient.get_corporate_actions` does the same at
the parse level, skipping one bad row instead of failing the whole page.

The upsert is issue #5's shared `ingest.sinks.upsert_events`; `EventRow` is
that module's own dataclass, not a local stand-in. Split details go
through issue #5's `ingest.events.split_details` -- the one place that
shape is written, since `market_caps_rebuild` reads it back with
`split_ratio`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.alpaca.client import (
    CashDividendAction,
    CorporateActionsSource,
    NameChangeAction,
    SplitAction,
    require_alpaca_client,
)
from stockticker.ingest.common import ALPACA_SOURCE, HISTORY_START, active_symbols, chunked
from stockticker.ingest.events import split_details
from stockticker.ingest.job import FailedItem, JobContext, JobResult, JobSkipped
from stockticker.ingest.sinks import EventRow, upsert_events
from stockticker.timeutil import today_ny

JOB_NAME = "corporate_actions_sync"
BATCH_SIZE = 50
LOOKBACK_DAYS = 30
ACTION_TYPES = ("forward_split", "reverse_split", "cash_dividend", "name_change")
BOOTSTRAP_KEY_PREFIX = "bootstrapped:"

# Canonical dot-form ticker (system design §4, symbol normalization):
# 1-6 letters, an optional one-to-three-letter share class after a dot.
# A 10-char cap leaves headroom without accepting garbage.
_TICKER_PATTERN = re.compile(r"^[A-Z]{1,6}(\.[A-Z]{1,3})?$")
_TICKER_LENGTH_CAP = 10

CorporateAction = SplitAction | CashDividendAction | NameChangeAction


async def corporate_actions_sync(ctx: JobContext) -> JobResult:
    client = require_alpaca_client()
    return await run_corporate_actions_sync(ctx.engine, client)


async def run_corporate_actions_sync(engine: AsyncEngine, client: CorporateActionsSource) -> JobResult:
    async with engine.connect() as conn:
        symbols = await active_symbols(conn, include_inactive=True)
    if not symbols:
        raise JobSkipped("no Listings")

    end = today_ny()
    rows_written = 0
    failed_items: list[FailedItem] = []
    for batch in chunked(symbols, BATCH_SIZE):
        async with engine.connect() as conn:
            bootstrapped = await _bootstrapped_symbols(conn, batch)
        # A mixed-bootstrap batch still makes one request per symbol's own
        # start date would ideally be per-symbol, but Alpaca's endpoint
        # takes one range per call -- use the widest start any member of
        # this batch needs, same trade-off as bars_backfill's shared fetch.
        start = HISTORY_START if len(bootstrapped) < len(batch) else end - timedelta(days=LOOKBACK_DAYS)

        try:
            page = await client.get_corporate_actions(batch, types=ACTION_TYPES, start=start, end=end)
        except Exception as exc:  # noqa: BLE001 - the whole batch failed, retried next run
            failed_items.extend(FailedItem(key=symbol, error=str(exc)) for symbol in batch)
            continue

        failed_items.extend(FailedItem(key="parse", error=error) for error in page.errors)

        async with engine.connect() as conn:
            cik_by_symbol = await _cik_by_symbol(conn, batch)
            rows: list[EventRow] = []
            actions: list[CorporateAction] = [*page.splits, *page.dividends, *page.name_changes]
            for action in actions:
                outcome = to_event(action, cik_by_symbol)
                if isinstance(outcome, FailedItem):
                    failed_items.append(outcome)
                else:
                    rows.append(outcome)
            upsert_result = await upsert_events(conn, rows)
            rows_written += upsert_result.rows_written
            failed_items.extend(upsert_result.failed_items)
            for symbol in batch:
                if symbol not in bootstrapped:
                    await _mark_bootstrapped(conn, symbol)
            await conn.commit()

    return JobResult(rows_written=rows_written, failed_items=failed_items)


def to_event(action: CorporateAction, cik_by_symbol: dict[str, str]) -> EventRow | FailedItem:
    if isinstance(action, SplitAction):
        return _split_to_event(action, cik_by_symbol)
    if isinstance(action, CashDividendAction):
        return _dividend_to_event(action, cik_by_symbol)
    return _name_change_to_event(action, cik_by_symbol)


def _split_to_event(action: SplitAction, cik_by_symbol: dict[str, str]) -> EventRow | FailedItem:
    cik = cik_by_symbol.get(action.symbol)
    if cik is None:
        return FailedItem(key=action.symbol, error="no listing for symbol")
    kind = "reverse_split" if action.reverse else "split"
    title = f"{_format_decimal(action.new_rate)}-for-{_format_decimal(action.old_rate)} split"
    return EventRow(
        cik=cik,
        symbol=action.symbol,
        event_date=action.ex_date,
        kind=kind,
        title=title,
        details=cast("dict[str, object]", split_details(action.old_rate, action.new_rate)),
        source=ALPACA_SOURCE,
        source_ref=f"split:{action.id}",
    )


def _dividend_to_event(action: CashDividendAction, cik_by_symbol: dict[str, str]) -> EventRow | FailedItem:
    cik = cik_by_symbol.get(action.symbol)
    if cik is None:
        return FailedItem(key=action.symbol, error="no listing for symbol")
    return EventRow(
        cik=cik,
        symbol=action.symbol,
        event_date=action.ex_date,
        kind="cash_dividend",
        title=f"Cash dividend ${_format_decimal(action.rate)}",
        details={"rate": str(action.rate)},
        source=ALPACA_SOURCE,
        source_ref=f"dividend:{action.id}",
    )


def _name_change_to_event(action: NameChangeAction, cik_by_symbol: dict[str, str]) -> EventRow | FailedItem:
    for symbol in (action.old_symbol, action.new_symbol):
        if not _is_valid_ticker(symbol):
            return FailedItem(key=action.old_symbol, error=f"invalid ticker {symbol!r}")
    cik = cik_by_symbol.get(action.old_symbol)
    if cik is None:
        return FailedItem(key=action.old_symbol, error="no listing for old symbol")
    return EventRow(
        cik=cik,
        symbol=action.old_symbol,
        event_date=action.process_date,
        kind="symbol_change",
        title=f"{action.old_symbol} → {action.new_symbol}",
        details={"old_symbol": action.old_symbol, "new_symbol": action.new_symbol},
        source=ALPACA_SOURCE,
        source_ref=f"name_change:{action.id}",
    )


def _is_valid_ticker(symbol: str) -> bool:
    return len(symbol) <= _TICKER_LENGTH_CAP and bool(_TICKER_PATTERN.match(symbol))


def _format_decimal(value: Decimal) -> str:
    text_value = format(value.normalize(), "f")
    if "." in text_value:
        text_value = text_value.rstrip("0").rstrip(".")
    return text_value or "0"


async def _cik_by_symbol(conn: AsyncConnection, symbols: Sequence[str]) -> dict[str, str]:
    stmt = text("SELECT symbol, cik FROM listings WHERE symbol IN :symbols").bindparams(
        bindparam("symbols", expanding=True)
    )
    rows = (await conn.execute(stmt, {"symbols": list(symbols)})).all()
    return {row.symbol: row.cik for row in rows}


async def _bootstrapped_symbols(conn: AsyncConnection, symbols: Sequence[str]) -> set[str]:
    stmt = text("SELECT key FROM ingest_watermarks WHERE job = :job_name AND key IN :keys").bindparams(
        bindparam("keys", expanding=True)
    )
    keys = [f"{BOOTSTRAP_KEY_PREFIX}{symbol}" for symbol in symbols]
    rows = (await conn.execute(stmt, {"job_name": JOB_NAME, "keys": keys})).all()
    await conn.commit()
    return {row.key.removeprefix(BOOTSTRAP_KEY_PREFIX) for row in rows}


async def _mark_bootstrapped(conn: AsyncConnection, symbol: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO ingest_watermarks (job, key, value, updated_at) "
            "VALUES (:job_name, :key, :value, now()) "
            "ON CONFLICT (job, key) DO UPDATE SET updated_at = excluded.updated_at"
        ),
        {"job_name": JOB_NAME, "key": f"{BOOTSTRAP_KEY_PREFIX}{symbol}", "value": HISTORY_START.isoformat()},
    )


__all__ = [
    "ACTION_TYPES",
    "BATCH_SIZE",
    "JOB_NAME",
    "LOOKBACK_DAYS",
    "corporate_actions_sync",
    "run_corporate_actions_sync",
    "to_event",
]
