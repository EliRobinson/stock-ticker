"""`to_event` -- one corporate action in, one `EventRow` or `FailedItem`
out -- against fakes only, no HTTP or database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stockticker.ingest.alpaca.client import CashDividendAction, NameChangeAction, SplitAction
from stockticker.ingest.job import FailedItem
from stockticker.ingest.jobs.corporate_actions_sync import to_event
from stockticker.ingest.sinks import EventRow

CIK_BY_SYMBOL = {"AAPL": "0000320193", "FB": "0001326801"}


def test_split_becomes_an_event_with_a_normalized_title() -> None:
    action = SplitAction(
        id="split-1",
        symbol="AAPL",
        old_rate=Decimal("1.00"),
        new_rate=Decimal("4.00"),
        ex_date=date(2020, 8, 31),
        reverse=False,
    )
    event = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(event, EventRow)
    assert event.title == "4-for-1 split"  # not "4.00-for-1.00"
    assert event.kind == "split"
    assert event.cik == "0000320193"
    assert event.symbol == "AAPL"


def test_reverse_split_kind() -> None:
    action = SplitAction(
        id="split-2",
        symbol="AAPL",
        old_rate=Decimal("10"),
        new_rate=Decimal("1"),
        ex_date=date(2020, 1, 1),
        reverse=True,
    )
    event = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(event, EventRow)
    assert event.kind == "reverse_split"


def test_dividend_title_is_normalized() -> None:
    action = CashDividendAction(id="div-1", symbol="AAPL", rate=Decimal("0.240"), ex_date=date(2020, 8, 7))
    event = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(event, EventRow)
    assert event.title == "Cash dividend $0.24"


def test_name_change_links_through_the_old_symbol() -> None:
    action = NameChangeAction(
        id="rename-1", old_symbol="FB", new_symbol="META", process_date=date(2022, 6, 9)
    )
    event = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(event, EventRow)
    assert event.cik == "0001326801"
    assert event.symbol == "FB"
    assert event.kind == "symbol_change"


def test_a_symbol_with_no_listing_is_a_failed_item() -> None:
    action = SplitAction(
        id="split-3",
        symbol="ZZZZ",
        old_rate=Decimal("1"),
        new_rate=Decimal("2"),
        ex_date=date(2020, 1, 1),
        reverse=False,
    )
    outcome = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(outcome, FailedItem)
    assert outcome.key == "ZZZZ"


def test_a_name_change_with_an_invalid_new_symbol_is_a_failed_item() -> None:
    action = NameChangeAction(
        id="rename-2", old_symbol="AAPL", new_symbol="not a ticker!!", process_date=date(2020, 1, 1)
    )
    outcome = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(outcome, FailedItem)


def test_a_name_change_with_an_overlong_symbol_is_a_failed_item() -> None:
    action = NameChangeAction(
        id="rename-3", old_symbol="AAPL", new_symbol="ABCDEFGHIJK", process_date=date(2020, 1, 1)
    )
    outcome = to_event(action, CIK_BY_SYMBOL)
    assert isinstance(outcome, FailedItem)


def test_a_valid_share_class_ticker_is_accepted() -> None:
    action = NameChangeAction(
        id="rename-4", old_symbol="AAPL", new_symbol="BRK.B", process_date=date(2020, 1, 1)
    )
    outcome = to_event(action, {**CIK_BY_SYMBOL, "AAPL": "0000320193"})
    assert isinstance(outcome, EventRow)
