from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from stockticker.ingest.edgar.parse import (
    DEI_SHARES,
    US_GAAP_SHARES,
    filing_title,
    parse_filings,
    parse_shares,
)
from stockticker.ingest.edgar.sync import (
    EDGAR_BASE_URL,
    build_edgar_client,
    fetch_companyfacts,
    fetch_submissions,
)
from stockticker.ingest.http import reset_rate_budgets

FIXTURES = Path(__file__).parent.parent / "fixtures" / "edgar"
AAPL_CIK = "0000320193"
GOOGL_CIK = "0001652044"
USER_AGENT = "Jane Doe jane@example.com"


def _fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


@pytest.fixture(autouse=True)
def _reset_budgets() -> Iterator[None]:
    reset_rate_budgets()
    yield
    reset_rate_budgets()


def test_parse_shares_keeps_both_concepts_since_2016() -> None:
    parsed = parse_shares(_fixture("companyfacts_aapl.json"))

    by_concept = {
        concept: [f for f in parsed.facts if f.concept == concept] for concept in (DEI_SHARES, US_GAAP_SHARES)
    }
    assert len(by_concept[DEI_SHARES]) == 6  # the 2015 cover count is dropped
    assert len(by_concept[US_GAAP_SHARES]) == 9
    assert parsed.rejected == []


def test_parse_shares_keys_each_count_by_accession() -> None:
    parsed = parse_shares(_fixture("companyfacts_aapl.json"))

    restated = [
        fact
        for fact in parsed.facts
        if fact.concept == US_GAAP_SHARES and fact.as_of_date == date(2019, 9, 28)
    ]
    assert {(fact.accession, fact.shares) for fact in restated} == {
        ("0000320193-20-000010", 4443236000),
        ("0000320193-20-000052", 4443236000),
        ("0000320193-20-000062", 4443236000),
        ("0000320193-20-000096", 17772945000),
    }
    ten_k = next(fact for fact in restated if fact.accession == "0000320193-20-000096")
    assert ten_k.form == "10-K"
    assert ten_k.filed_date == date(2020, 10, 30)


def test_parse_shares_falls_back_to_us_gaap_when_dei_is_absent() -> None:
    parsed = parse_shares(_fixture("companyfacts_googl.json"))

    assert {fact.concept for fact in parsed.facts} == {US_GAAP_SHARES}
    assert len(parsed.facts) == 11


def _facts_with(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": entries}}}}}


def test_parse_shares_rejects_a_zero_count() -> None:
    parsed = parse_shares(
        _facts_with([{"end": "2020-04-30", "val": 0, "accn": "A-1", "form": "10-Q", "filed": "2020-05-07"}])
    )

    assert parsed.facts == []
    assert parsed.rejected == [(f"2020-04-30:{DEI_SHARES}:A-1", "shares outstanding is 0")]


def test_parse_shares_rejects_conflicting_counts_in_one_filing() -> None:
    entry = {"end": "2020-04-30", "accn": "A-1", "form": "10-Q", "filed": "2020-05-07"}
    parsed = parse_shares(_facts_with([{**entry, "val": 100}, {**entry, "val": 200}, {**entry, "val": 100}]))

    assert parsed.facts == []
    assert parsed.rejected[0][1] == "conflicting counts in one filing: [100, 200]"


def test_parse_shares_collapses_identical_duplicates() -> None:
    entry = {"end": "2020-04-30", "val": 100, "accn": "A-1", "form": "10-Q", "filed": "2020-05-07"}
    parsed = parse_shares(_facts_with([entry, dict(entry)]))

    assert len(parsed.facts) == 1


def test_parse_shares_skips_malformed_entries() -> None:
    parsed = parse_shares(_facts_with([{"end": "2020-04-30", "val": 100}]))

    assert parsed.facts == []
    assert parsed.rejected == []


def test_parse_filings_keeps_10k_10q_8k_since_2018() -> None:
    events = parse_filings(_fixture("submissions_aapl.json"), AAPL_CIK)

    assert [(event.kind, event.event_date) for event in events] == [
        ("filing_10q", date(2026, 7, 31)),
        ("filing_8k", date(2026, 7, 30)),
        ("filing_8k", date(2026, 2, 24)),
        ("filing_10k", date(2025, 10, 31)),
    ]


def test_parse_filings_details_carry_accession_and_document_url() -> None:
    ten_q = parse_filings(_fixture("submissions_aapl.json"), AAPL_CIK)[0]

    assert ten_q.title == "Quarterly report (10-Q)"
    assert ten_q.accession == "0000320193-26-000020"
    assert ten_q.details == {
        "accession": "0000320193-26-000020",
        "form": "10-Q",
        "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/aapl-20260627.htm",
        "report_date": "2026-06-27",
    }


def test_parse_filings_titles_8k_from_its_items() -> None:
    events = parse_filings(_fixture("submissions_aapl.json"), AAPL_CIK)
    earnings, vote = events[1], events[2]

    assert earnings.title == "Results of operations (8-K)"
    assert earnings.details["items"] == ["2.02", "9.01"]
    assert earnings.details["item_names"] == ["Results of operations", "Financial statements and exhibits"]
    assert vote.title == "Shareholder vote results (8-K)"


@pytest.mark.parametrize(
    ("items", "title"),
    [
        ([], "Current report (8-K)"),
        (["9.01"], "Financial statements and exhibits (8-K)"),
        (["2.01", "5.02", "9.01"], "Acquisition or disposition completed; Director or officer change (8-K)"),
        (["9.99"], "Item 9.99 (8-K)"),
    ],
)
def test_filing_title_for_8k(items: list[str], title: str) -> None:
    assert filing_title("8-K", items) == title


def test_parse_filings_tolerates_an_empty_submissions_document() -> None:
    assert parse_filings({}, AAPL_CIK) == []


@respx.mock
async def test_fetches_go_to_data_sec_gov_with_the_user_agent() -> None:
    facts = respx.get(f"{EDGAR_BASE_URL}/api/xbrl/companyfacts/CIK{AAPL_CIK}.json").mock(
        return_value=httpx.Response(200, json=_fixture("companyfacts_aapl.json"))
    )
    submissions = respx.get(f"{EDGAR_BASE_URL}/submissions/CIK{AAPL_CIK}.json").mock(
        return_value=httpx.Response(200, json=_fixture("submissions_aapl.json"))
    )

    async with build_edgar_client(USER_AGENT) as client:
        facts_json = await fetch_companyfacts(client, AAPL_CIK)
        submissions_json = await fetch_submissions(client, AAPL_CIK)

    assert facts_json is not None and facts_json["entityName"] == "Apple Inc."
    assert submissions_json["name"] == "Apple Inc."
    for route in (facts, submissions):
        request = route.calls[0].request
        assert request.url.host == "data.sec.gov"
        assert request.headers["User-Agent"] == USER_AGENT


@respx.mock
async def test_companyfacts_404_means_no_facts() -> None:
    respx.get(f"{EDGAR_BASE_URL}/api/xbrl/companyfacts/CIK{GOOGL_CIK}.json").mock(
        return_value=httpx.Response(404)
    )

    async with build_edgar_client(USER_AGENT) as client:
        assert await fetch_companyfacts(client, GOOGL_CIK) is None


@respx.mock
async def test_submissions_404_is_an_error() -> None:
    respx.get(f"{EDGAR_BASE_URL}/submissions/CIK{GOOGL_CIK}.json").mock(return_value=httpx.Response(404))

    async with build_edgar_client(USER_AGENT) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_submissions(client, GOOGL_CIK)
