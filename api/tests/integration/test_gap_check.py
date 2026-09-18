"""`gap_check` against Postgres. Each test runs in one transaction that is
rolled back; it first marks every existing Listing inactive inside that
transaction and uses Trading Days in 1990, which no real data reaches.
See tests/integration/conftest.py for how to run these."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from stockticker.ingest.gap_check import check_gaps
from stockticker.ingest.job import JobSkipped
from stockticker.ingest.refetch import (
    GAP_STILL_OPEN,
    MAX_GAP_ATTEMPTS,
    finish_refetch,
    mark_refetch_failed,
)

DAYS = [date(1990, 1, day) for day in (2, 3, 4, 5, 8, 9, 10, 11, 12)]


@pytest_asyncio.fixture
async def conn(app_writer_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with app_writer_engine.connect() as connection:
        await connection.execute(text("UPDATE listings SET is_active = false WHERE is_active"))
        await connection.execute(text("DELETE FROM ingest_watermarks WHERE job = 'gap_check'"))
        for day in DAYS:
            opens = datetime.combine(day, time(14, 30), tzinfo=UTC)
            await connection.execute(
                text(
                    "INSERT INTO trading_days (trade_date, open_at, close_at) VALUES (:d, :o, :c) "
                    "ON CONFLICT (trade_date) DO NOTHING"
                ),
                {"d": day, "o": opens, "c": opens + timedelta(hours=6, minutes=30)},
            )
        yield connection
        await connection.rollback()


async def _listing(
    conn: AsyncConnection, bar_days: list[date], *, backfilled: bool = True, active: bool = True
) -> str:
    cik = f"8{uuid.uuid4().int % 10**9:09d}"
    symbol = f"G{uuid.uuid4().hex[:6].upper()}"
    await conn.execute(
        text("INSERT INTO companies (cik, name, sector) VALUES (:cik, 'Gap Co', 'Test')"), {"cik": cik}
    )
    await conn.execute(
        text(
            "INSERT INTO listings "
            "(symbol, cik, is_primary, is_active, first_bar_date, backfill_completed_at) "
            "VALUES (:s, :cik, true, :active, :first, :done)"
        ),
        {
            "s": symbol,
            "cik": cik,
            "active": active,
            "first": DAYS[0],
            "done": datetime.now(UTC) if backfilled else None,
        },
    )
    for day in bar_days:
        await _add_bar(conn, symbol, day)
    return symbol


async def _add_bar(conn: AsyncConnection, symbol: str, day: date) -> None:
    await conn.execute(
        text(
            "INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, adj_close, source, "
            "ingested_at) VALUES (:s, :d, 1, 1, 1, 1, 0, 1, 'test', now())"
        ),
        {"s": symbol, "d": day},
    )


async def _request(conn: AsyncConnection, symbol: str, reason: str = "gap") -> Any:
    result = await conn.execute(
        text(
            "SELECT from_date, attempts, last_error, accepted_at, requested_at "
            "FROM refetch_requests WHERE symbol = :s AND reason = :r"
        ),
        {"s": symbol, "r": reason},
    )
    return result.one_or_none()


async def _fail(conn: AsyncConnection, symbol: str) -> None:
    """What bars_backfill does when its re-fetch raises (issue #4)."""
    await mark_refetch_failed(conn, symbol, "gap", "provider returned 500")


async def _drop_bar(conn: AsyncConnection, symbol: str, day: date) -> None:
    await conn.execute(
        text("DELETE FROM daily_bars WHERE symbol = :s AND trade_date = :d"), {"s": symbol, "d": day}
    )


def _without(*missing: date) -> list[date]:
    return [day for day in DAYS if day not in missing]


async def test_a_gap_is_queued_from_its_first_missing_day(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[3], DAYS[5]))

    summary = await check_gaps(conn)

    request = await _request(conn, symbol)
    assert request.from_date == DAYS[3]
    assert request.attempts == 0
    assert request.accepted_at is None
    assert summary.queued == 1


async def test_complete_listings_queue_nothing(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, DAYS)

    summary = await check_gaps(conn)

    assert await _request(conn, symbol) is None
    assert summary.queued == 0


async def test_days_after_the_latest_bar_are_not_gaps(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, DAYS[:4])

    await check_gaps(conn)

    assert await _request(conn, symbol) is None


async def test_only_backfilled_active_listings_are_checked(conn: AsyncConnection) -> None:
    pending = await _listing(conn, _without(DAYS[2]), backfilled=False)
    retired = await _listing(conn, _without(DAYS[2]), active=False)
    checked = await _listing(conn, _without(DAYS[2]))

    await check_gaps(conn)

    assert await _request(conn, pending) is None
    assert await _request(conn, retired) is None
    assert await _request(conn, checked) is not None


async def test_no_listing_in_scope_skips_the_run(conn: AsyncConnection) -> None:
    await _listing(conn, _without(DAYS[2]), backfilled=False)

    with pytest.raises(JobSkipped):
        await check_gaps(conn)


async def test_a_request_being_retried_is_left_waiting(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    await _fail(conn, symbol)

    summary = await check_gaps(conn)

    assert (await _request(conn, symbol)).attempts == 1
    assert summary.waiting == 1


async def test_an_earlier_gap_widens_a_waiting_request(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    # `now()` is transaction-stable; pin an older stamp so a real widen's
    # renew is observable inside this test's single transaction.
    await conn.execute(
        text("UPDATE refetch_requests SET requested_at = :t WHERE symbol = :s AND reason = 'gap'"),
        {"s": symbol, "t": datetime(2020, 1, 1, tzinfo=UTC)},
    )
    await _drop_bar(conn, symbol, DAYS[1])

    await check_gaps(conn)

    request = await _request(conn, symbol)
    assert request.from_date == DAYS[1]
    assert request.requested_at > datetime(2020, 1, 1, tzinfo=UTC)


async def test_a_noop_widen_does_not_renew_requested_at(conn: AsyncConnection) -> None:
    """gap_check calls _widen every night for every waiting row. Renewing
    `requested_at` when `from_date` is unchanged would defeat finish_refetch
    after an overlapping bars_backfill."""
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    pinned = datetime(2020, 1, 1, tzinfo=UTC)
    await conn.execute(
        text("UPDATE refetch_requests SET requested_at = :t WHERE symbol = :s AND reason = 'gap'"),
        {"s": symbol, "t": pinned},
    )

    await check_gaps(conn)

    request = await _request(conn, symbol)
    assert request.from_date == DAYS[4]
    assert request.requested_at == pinned


async def test_a_gap_is_accepted_after_three_failed_refetches(conn: AsyncConnection) -> None:
    """The real failure path: the serving job's mark_refetch_failed. Before
    the DRY pass, a failed gap re-fetch left no trace and the gap could
    never be accepted."""
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    for attempt in range(1, MAX_GAP_ATTEMPTS + 1):
        await _fail(conn, symbol)
        assert (await _request(conn, symbol)).attempts == attempt

    summary = await check_gaps(conn)

    request = await _request(conn, symbol)
    assert request.accepted_at is not None
    assert request.last_error == "provider returned 500"
    assert summary.accepted == 1
    later = await check_gaps(conn)
    assert (later.queued, later.waiting, later.accepted) == (0, 0, 0)


async def test_a_refetch_that_leaves_the_gap_open_counts_as_a_failed_attempt(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)

    await finish_refetch(conn, symbol, "gap", datetime.now(UTC))

    request = await _request(conn, symbol)
    assert request.attempts == 1
    assert request.last_error == GAP_STILL_OPEN


async def test_three_refetches_with_no_bar_for_the_day_accept_the_gap(conn: AsyncConnection) -> None:
    """A halted day: the provider has no bar, so every re-fetch commits and
    the gap stays open."""
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    for _ in range(MAX_GAP_ATTEMPTS):
        await finish_refetch(conn, symbol, "gap", datetime.now(UTC))

    summary = await check_gaps(conn)

    assert summary.accepted == 1
    assert (await _request(conn, symbol)).accepted_at is not None


async def test_a_refetch_that_closes_the_gap_deletes_the_request(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    await _add_bar(conn, symbol, DAYS[4])

    await finish_refetch(conn, symbol, "gap", datetime.now(UTC))

    assert await _request(conn, symbol) is None


async def test_a_request_renewed_during_the_refetch_is_kept(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    selected_at = datetime.now(UTC) - timedelta(minutes=5)
    await check_gaps(conn)
    await _add_bar(conn, symbol, DAYS[4])

    await finish_refetch(conn, symbol, "gap", selected_at)

    assert await _request(conn, symbol) is not None


async def test_adj_drift_rows_share_the_failure_and_finish_paths(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, DAYS)
    await conn.execute(
        text("INSERT INTO refetch_requests (symbol, reason, from_date) VALUES (:s, 'adj_drift', :d)"),
        {"s": symbol, "d": DAYS[0]},
    )

    await mark_refetch_failed(conn, symbol, "adj_drift", "x" * 900)
    failed = await _request(conn, symbol, "adj_drift")
    await finish_refetch(conn, symbol, "adj_drift", datetime.now(UTC))

    assert failed.attempts == 1
    assert len(failed.last_error) == 500
    assert await _request(conn, symbol, "adj_drift") is None


async def test_a_new_gap_after_acceptance_starts_a_fresh_cycle(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    for _ in range(MAX_GAP_ATTEMPTS):
        await _fail(conn, symbol)
    await check_gaps(conn)
    await _drop_bar(conn, symbol, DAYS[6])

    await check_gaps(conn)

    request = await _request(conn, symbol)
    assert request.accepted_at is None
    assert request.attempts == 0
    assert request.from_date == DAYS[6]


async def test_accepted_days_do_not_keep_a_later_refetch_open(conn: AsyncConnection) -> None:
    symbol = await _listing(conn, _without(DAYS[4]))
    await check_gaps(conn)
    for _ in range(MAX_GAP_ATTEMPTS):
        await _fail(conn, symbol)
    await check_gaps(conn)
    await _drop_bar(conn, symbol, DAYS[6])
    await check_gaps(conn)
    await _add_bar(conn, symbol, DAYS[6])

    await finish_refetch(conn, symbol, "gap", datetime.now(UTC))

    assert await _request(conn, symbol) is None
