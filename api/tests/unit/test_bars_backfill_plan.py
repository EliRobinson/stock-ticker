"""`plan_symbol_outcomes` -- per-symbol resume filtering, watermark
computation, and backfill-completion detection -- against fakes only, no
HTTP or database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stockticker.ingest.jobs.bars_backfill import SymbolBackfillPlan, plan_symbol_outcomes
from stockticker.ingest.providers import ProviderBar


def _bar(symbol: str, d: date, close: str) -> ProviderBar:
    return ProviderBar(
        symbol=symbol,
        trade_date=d,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=100,
        adj_close=Decimal(close),
        source="alpaca",
    )


def test_plan_keeps_only_this_symbols_bars() -> None:
    bars = [_bar("AAPL", date(2026, 1, 2), "10"), _bar("MSFT", date(2026, 1, 2), "99")]
    plans = [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2018, 1, 1), first_run=True)]

    outcomes = plan_symbol_outcomes(bars, plans, end_trading_day=date(2026, 1, 5))

    outcome = outcomes["AAPL"]
    assert [row.trade_date for row in outcome.rows] == [date(2026, 1, 2)]
    assert outcome.rows[0].close == Decimal("10")


def test_plan_drops_rows_before_the_symbols_own_resume_point() -> None:
    """A batch call can return dates earlier than one symbol's resume point
    when another symbol in the same batch needed an earlier `start` --
    those earlier rows must not be re-applied for the already-advanced
    symbol."""
    bars = [_bar("AAPL", date(2020, 1, 2), "5"), _bar("AAPL", date(2026, 1, 2), "10")]
    plans = [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2025, 1, 1), first_run=False)]

    outcomes = plan_symbol_outcomes(bars, plans, end_trading_day=date(2026, 1, 2))

    assert [row.trade_date for row in outcomes["AAPL"].rows] == [date(2026, 1, 2)]


def test_watermark_is_the_latest_row_date() -> None:
    bars = [_bar("AAPL", date(2026, 1, 2), "1"), _bar("AAPL", date(2026, 1, 5), "2")]
    plans = [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2018, 1, 1), first_run=True)]

    outcome = plan_symbol_outcomes(bars, plans, end_trading_day=date(2026, 2, 1))["AAPL"]

    assert outcome.watermark == date(2026, 1, 5)
    assert outcome.completed is False  # watermark hasn't caught up to end_trading_day yet


def test_watermark_at_end_trading_day_marks_the_symbol_completed() -> None:
    bars = [_bar("AAPL", date(2026, 1, 5), "1")]
    plans = [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2026, 1, 5), first_run=False)]

    outcome = plan_symbol_outcomes(bars, plans, end_trading_day=date(2026, 1, 5))["AAPL"]

    assert outcome.completed is True


def test_first_bar_date_is_only_set_on_a_first_run() -> None:
    bars = [_bar("AAPL", date(2018, 1, 2), "1")]

    first_run = plan_symbol_outcomes(
        bars,
        [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2018, 1, 1), first_run=True)],
        end_trading_day=date(2026, 1, 1),
    )["AAPL"]
    assert first_run.first_bar_date == date(2018, 1, 2)

    resume_run = plan_symbol_outcomes(
        bars,
        [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2018, 1, 1), first_run=False)],
        end_trading_day=date(2026, 1, 1),
    )["AAPL"]
    assert resume_run.first_bar_date is None


def test_a_symbol_with_no_rows_in_its_window_is_marked_completed() -> None:
    """Review fix: a delisted-before-2018 or halted symbol has nothing in
    any window it's ever given -- if that weren't completion, it would
    hold a batch slot forever and starve the other ~500 symbols."""
    plans = [SymbolBackfillPlan(symbol="AAPL", resume_from=date(2018, 1, 1), first_run=True)]
    outcome = plan_symbol_outcomes([], plans, end_trading_day=date(2026, 1, 1))["AAPL"]
    assert outcome.rows == []
    assert outcome.watermark is None
    assert outcome.completed is True


def test_refetch_reasons_is_reset_to_from_date() -> None:
    """A drift or gap refetch resets the plan's `resume_from` to the
    request's `from_date` (issue #4 review comment 1) -- the plan then
    naturally rewrites the symbol's whole requested range."""
    bars = [_bar("AAPL", date(2018, 1, 2), "1"), _bar("AAPL", date(2020, 6, 1), "2")]
    plan = SymbolBackfillPlan(
        symbol="AAPL", resume_from=date(2018, 1, 1), first_run=False, refetch_reasons=frozenset({"adj_drift"})
    )

    outcome = plan_symbol_outcomes(bars, [plan], end_trading_day=date(2026, 1, 1))["AAPL"]

    assert [row.trade_date for row in outcome.rows] == [date(2018, 1, 2), date(2020, 6, 1)]


def test_a_symbol_with_both_a_gap_and_an_adj_drift_row_gets_one_plan_serving_both() -> None:
    """Correctness review finding 1: a symbol queued for both a drift
    rewrite (from 2018-01-01) and a gap fill (from a later date) must not
    lose the wider drift range to whichever plan the caller happens to
    build last -- resume_from is the min of both, and both reasons ride
    the one plan."""
    plan = SymbolBackfillPlan(
        symbol="AAPL",
        resume_from=date(2018, 1, 1),  # the min of the drift row's and the gap row's from_date
        first_run=False,
        refetch_reasons=frozenset({"adj_drift", "gap"}),
    )
    bars = [_bar("AAPL", date(2018, 1, 2), "1"), _bar("AAPL", date(2024, 3, 1), "2")]

    outcome = plan_symbol_outcomes(bars, [plan], end_trading_day=date(2026, 1, 1))["AAPL"]

    assert [row.trade_date for row in outcome.rows] == [date(2018, 1, 2), date(2024, 3, 1)]
    assert plan.refetch_reasons == frozenset({"adj_drift", "gap"})
