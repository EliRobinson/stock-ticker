"""The Python half of the Market Cap rules: split ratios and the §3 sanity
checks. The price x shares math is SQL and is tested against Postgres in
tests/integration/test_market_caps_math.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stockticker.ingest.edgar.parse import DEI_SHARES, US_GAAP_SHARES
from stockticker.ingest.market_caps import ShareCount, SplitRatioError, split_ratio, validate_counts


def count(
    as_of: str, filed: str, shares: int, *, concept: str = DEI_SHARES, accession: str | None = None
) -> ShareCount:
    return ShareCount(
        as_of_date=date.fromisoformat(as_of),
        filed_date=date.fromisoformat(filed),
        concept=concept,
        accession=accession or f"acc-{as_of}-{filed}",
        shares=shares,
    )


@pytest.mark.parametrize(
    ("kind", "details", "expected"),
    [
        ("split", {"ratio": 4}, Decimal(4)),
        ("split", {"ratio": "1.5"}, Decimal("1.5")),
        ("split", {"new_rate": 20, "old_rate": 1}, Decimal(20)),
        ("reverse_split", {"new_rate": 1, "old_rate": 10}, Decimal("0.1")),
        ("reverse_split", {"ratio": "0.125"}, Decimal("0.125")),
        ("reverse_split", {"ratio": 8}, Decimal("0.125")),
    ],
)
def test_split_ratio_is_new_shares_per_old_share(
    kind: str, details: dict[str, object], expected: Decimal
) -> None:
    assert split_ratio(kind, details) == expected


@pytest.mark.parametrize(
    "details",
    [{}, {"new_rate": 2}, {"new_rate": 2, "old_rate": 0}, {"ratio": "abc"}, {"ratio": 0}, {"ratio": -2}],
)
def test_split_ratio_rejects_unusable_details(details: dict[str, object]) -> None:
    with pytest.raises(SplitRatioError):
        split_ratio("split", details)


def test_steady_counts_are_all_accepted() -> None:
    counts = [
        count("2020-01-17", "2020-01-29", 4_375_480_000),
        count("2020-04-17", "2020-05-01", 4_334_335_000),
        count("2020-07-17", "2020-07-31", 4_275_634_000),
    ]

    accepted, rejected = validate_counts(counts, [])

    assert accepted == counts
    assert rejected == []


def test_a_zero_count_is_rejected() -> None:
    zero = count("2020-04-30", "2020-05-07", 0)

    accepted, rejected = validate_counts([zero], [])

    assert accepted == []
    assert [r.reason for r in rejected] == ["shares outstanding is 0"]


def test_a_count_dated_after_its_filing_is_rejected() -> None:
    future = count("2020-06-30", "2020-05-07", 100)

    accepted, rejected = validate_counts([future], [])

    assert accepted == []
    assert rejected[0].reason == "count dated 2020-06-30, after its filing on 2020-05-07"


def test_a_jump_over_40_percent_with_nothing_in_between_is_rejected() -> None:
    before = count("2020-01-17", "2020-01-29", 1_000_000)
    jump = count("2020-04-17", "2020-05-01", 1_410_000)

    accepted, rejected = validate_counts([before, jump], [])

    assert accepted == [before]
    assert rejected[0].count == jump
    assert "changed 41%" in rejected[0].reason


def test_a_drop_over_40_percent_is_rejected_too() -> None:
    before = count("2020-01-17", "2020-01-29", 1_000_000)
    drop = count("2020-04-17", "2020-05-01", 590_000)

    _, rejected = validate_counts([before, drop], [])

    assert [r.count for r in rejected] == [drop]


def test_exactly_40_percent_is_allowed() -> None:
    before = count("2020-01-17", "2020-01-29", 1_000_000)
    edge = count("2020-04-17", "2020-05-01", 1_400_000)

    accepted, rejected = validate_counts([before, edge], [])

    assert accepted == [before, edge]
    assert rejected == []


@pytest.mark.parametrize("exempting_day", ["2020-03-02", "2020-01-18", "2020-05-01"])
def test_a_split_spin_off_or_merger_in_between_explains_a_jump(exempting_day: str) -> None:
    before = count("2020-01-17", "2020-01-29", 1_000_000)
    after = count("2020-04-17", "2020-05-01", 4_000_000)

    accepted, rejected = validate_counts([before, after], [date.fromisoformat(exempting_day)])

    assert accepted == [before, after]
    assert rejected == []


@pytest.mark.parametrize("outside_day", ["2020-01-17", "2019-12-31", "2020-05-02"])
def test_an_event_outside_the_window_does_not_explain_a_jump(outside_day: str) -> None:
    before = count("2020-01-17", "2020-01-29", 1_000_000)
    after = count("2020-04-17", "2020-05-01", 4_000_000)

    _, rejected = validate_counts([before, after], [date.fromisoformat(outside_day)])

    assert [r.count for r in rejected] == [after]


def test_a_rejected_count_never_becomes_the_baseline() -> None:
    good = count("2020-01-17", "2020-01-29", 1_000_000)
    typo = count("2020-04-17", "2020-05-01", 10_000_000)
    next_good = count("2020-07-17", "2020-07-31", 990_000)

    accepted, rejected = validate_counts([good, typo, next_good], [])

    assert accepted == [good, next_good]
    assert [r.count for r in rejected] == [typo]


def test_counts_are_checked_in_filing_order_not_input_order() -> None:
    later = count("2020-04-17", "2020-05-01", 1_000_000)
    earlier = count("2020-01-17", "2020-01-29", 5_000_000)

    accepted, rejected = validate_counts([later, earlier], [])

    assert accepted == [earlier]
    assert [r.count for r in rejected] == [later]


def test_alphabet_2022_restatements_pass_because_the_split_is_in_between() -> None:
    """Real EDGAR counts around Alphabet's 20-for-1 split (ex 2022-07-18). The
    post-split restatement of the 2021-12-31 count is filed after the split,
    so the jump is explained, and nothing real is rejected."""
    g = US_GAAP_SHARES
    counts = [
        count("2021-09-30", "2021-10-27", 664_682_000, concept=g),
        count("2021-12-31", "2022-02-02", 662_121_000, concept=g, accession="10-K 2021"),
        count("2021-12-31", "2022-04-27", 662_121_000, concept=g, accession="10-Q Q1"),
        count("2022-03-31", "2022-04-27", 658_763_000, concept=g, accession="10-Q Q1"),
        count("2021-12-31", "2022-07-27", 13_242_000_000, concept=g, accession="10-Q Q2"),
        count("2022-06-30", "2022-07-27", 13_078_000_000, concept=g, accession="10-Q Q2"),
        count("2022-09-30", "2022-10-26", 12_971_000_000, concept=g),
    ]

    accepted, rejected = validate_counts(counts, [date(2022, 7, 18)])

    assert rejected == []
    assert len(accepted) == len(counts)


def test_anchor_date_is_as_of_for_dei_and_filed_for_us_gaap() -> None:
    cover = count("2020-07-17", "2020-07-31", 1, concept=DEI_SHARES)
    balance_sheet = count("2020-06-27", "2020-07-31", 1, concept=US_GAAP_SHARES)

    assert cover.anchor_date == date(2020, 7, 17)
    assert balance_sheet.anchor_date == date(2020, 7, 31)
