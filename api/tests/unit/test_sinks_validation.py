"""`_bar_check_violation` mirrors `daily_bars`' own CHECK constraint
(migration 0001_initial_schema) so `upsert_bars` can turn a bad row into a
`FailedItem` instead of losing the whole batch (round 2 FIX-LATER, issue
#32). No database needed -- these are pure-Python invariant checks."""

from __future__ import annotations

from decimal import Decimal

from provider_bars import provider_bar

from stockticker.ingest.sinks import _bar_check_violation


def test_a_valid_bar_has_no_violation() -> None:
    assert _bar_check_violation(provider_bar()) is None


def test_low_must_be_positive() -> None:
    assert _bar_check_violation(provider_bar(low=Decimal("0"))) == "low must be > 0"
    assert _bar_check_violation(provider_bar(low=Decimal("-1"))) == "low must be > 0"


def test_low_must_not_exceed_the_lesser_of_open_and_close() -> None:
    bar = provider_bar(low=Decimal("10.20"), open=Decimal("10.00"), close=Decimal("10.10"))
    assert _bar_check_violation(bar) == "low must be <= least(open, close)"


def test_high_must_be_at_least_the_greater_of_open_and_close() -> None:
    bar = provider_bar(high=Decimal("10.50"), open=Decimal("10.00"), close=Decimal("11.00"))
    assert _bar_check_violation(bar) == "high must be >= greatest(open, close)"


def test_volume_must_not_be_negative() -> None:
    assert _bar_check_violation(provider_bar(volume=-1)) == "volume must be >= 0"


def test_zero_volume_is_allowed() -> None:
    assert _bar_check_violation(provider_bar(volume=0)) is None
