"""Pure parsing of EDGAR `companyfacts` and `submissions` JSON."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from stockticker.ingest.symbols import normalize_cik

DEI_SHARES = "dei:EntityCommonStockSharesOutstanding"
US_GAAP_SHARES = "us-gaap:CommonStockSharesOutstanding"
SHARES_CONCEPTS = (DEI_SHARES, US_GAAP_SHARES)

# Bars start 2018-01-01. A count reported during 2016-2017 can still be the
# latest one on the first Trading Days of 2018.
SHARES_SINCE = date(2016, 1, 1)
FILINGS_SINCE = date(2018, 1, 1)

# Only names of this shape are fetched, so a page name from the response
# can never steer a request off the fixed submissions path.
FILES_PAGE_NAME = re.compile(r"CIK\d{10}-submissions-\d{3}\.json")

FILING_KINDS = {"10-K": "filing_10k", "10-Q": "filing_10q", "8-K": "filing_8k"}
FILING_TITLES = {"10-K": "Annual report (10-K)", "10-Q": "Quarterly report (10-Q)"}
EXHIBITS_ITEM = "9.01"

# Form 8-K item codes -> short readable names.
EIGHT_K_ITEMS = {
    "1.01": "Material agreement",
    "1.02": "Material agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety shutdown",
    "1.05": "Cybersecurity incident",
    "2.01": "Acquisition or disposition completed",
    "2.02": "Results of operations",
    "2.03": "New financial obligation",
    "2.04": "Financial obligation accelerated",
    "2.05": "Exit or disposal costs",
    "2.06": "Material impairment",
    "3.01": "Delisting or listing transfer",
    "3.02": "Unregistered equity sale",
    "3.03": "Change to shareholder rights",
    "4.01": "Auditor change",
    "4.02": "Prior financials no longer reliable",
    "5.01": "Change in control",
    "5.02": "Director or officer change",
    "5.03": "Bylaws or fiscal year change",
    "5.04": "Benefit plan trading suspended",
    "5.05": "Code of ethics change",
    "5.06": "Shell company status change",
    "5.07": "Shareholder vote results",
    "5.08": "Shareholder director nominations",
    "6.01": "ABS informational material",
    "6.02": "ABS servicer or trustee change",
    "6.03": "ABS credit enhancement change",
    "6.04": "ABS distribution failure",
    "6.05": "ABS securities act updating",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
    EXHIBITS_ITEM: "Financial statements and exhibits",
}
MERGER_ITEM = "2.01"


@dataclass(frozen=True, slots=True)
class SharesFact:
    as_of_date: date
    concept: str
    accession: str
    form: str
    filed_date: date
    shares: int


@dataclass(frozen=True, slots=True)
class FilingEvent:
    kind: str
    event_date: date
    title: str
    accession: str
    details: dict[str, Any]


@dataclass(slots=True)
class SharesParse:
    facts: list[SharesFact] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (key, reason)


def cik_path(cik: str) -> str:
    return f"CIK{normalize_cik(cik)}"


def parse_shares(companyfacts: dict[str, Any]) -> SharesParse:
    """Every `dei:EntityCommonStockSharesOutstanding` and
    `us-gaap:CommonStockSharesOutstanding` fact, keyed by accession.

    Both concepts are stored. The rebuild's tie-break prefers `dei`, so
    `us-gaap` only decides a date when no `dei` count is available, which is
    the fallback. Issuers with several share classes (Alphabet) tag the cover
    page count per class, which companyfacts omits, so for them `us-gaap` is
    the only source.
    """
    result = SharesParse()
    by_key: dict[tuple[date, str, str], list[SharesFact]] = {}
    facts = companyfacts.get("facts") or {}
    for concept in SHARES_CONCEPTS:
        taxonomy, name = concept.split(":")
        entries = ((facts.get(taxonomy) or {}).get(name) or {}).get("units", {}).get("shares", [])
        for entry in entries:
            fact = _shares_fact(concept, entry)
            if fact is not None and fact.as_of_date >= SHARES_SINCE:
                by_key.setdefault((fact.as_of_date, fact.concept, fact.accession), []).append(fact)

    for (as_of_date, concept, accession), candidates in by_key.items():
        label = shares_key(as_of_date, concept, accession)
        counts = sorted({fact.shares for fact in candidates})
        if len(counts) > 1:
            result.rejected.append((label, f"conflicting counts in one filing: {counts}"))
        elif counts[0] <= 0:
            result.rejected.append((label, "shares outstanding is 0"))
        else:
            result.facts.append(candidates[0])
    return result


def shares_key(as_of_date: date, concept: str, accession: str) -> str:
    return f"{as_of_date.isoformat()}:{concept}:{accession}"


def _shares_fact(concept: str, entry: dict[str, Any]) -> SharesFact | None:
    try:
        return SharesFact(
            as_of_date=date.fromisoformat(entry["end"]),
            concept=concept,
            accession=str(entry["accn"]),
            form=str(entry.get("form") or ""),
            filed_date=date.fromisoformat(entry["filed"]),
            shares=int(entry["val"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def parse_filings(submissions: dict[str, Any], cik: str) -> list[FilingEvent]:
    """10-K, 10-Q, and 8-K filings from `filings.recent`, filed since 2018.
    Amendments (`10-K/A`, ...) are skipped. Older filings are in the pages
    `older_filing_pages` names; parse each with `parse_filings_page`."""
    return parse_filings_page((submissions.get("filings") or {}).get("recent") or {}, cik)


def older_filing_pages(submissions: dict[str, Any]) -> list[str]:
    """Names of the `filings.files[]` pages that reach 2018 or later. A heavy
    filer's `recent` block (the latest ~1000 filings of every form) can stop
    well short of 2018."""
    names = []
    for page in (submissions.get("filings") or {}).get("files") or []:
        name = str(page.get("name") or "")
        try:
            filing_to = date.fromisoformat(str(page.get("filingTo")))
        except ValueError:
            continue
        if FILES_PAGE_NAME.fullmatch(name) and filing_to >= FILINGS_SINCE:
            names.append(name)
    return names


def parse_filings_page(page: dict[str, Any], cik: str) -> list[FilingEvent]:
    """One block of filing columns: `filings.recent`, or a `files[]` page,
    which has the same columns at its top level."""
    accessions: list[str] = page.get("accessionNumber") or []
    columns = {
        name: page.get(name) or []
        for name in ("filingDate", "reportDate", "form", "items", "primaryDocument")
    }

    events: list[FilingEvent] = []
    for index, accession in enumerate(accessions):
        form = _at(columns["form"], index)
        if form not in FILING_KINDS:
            continue
        try:
            filed = date.fromisoformat(_at(columns["filingDate"], index))
        except ValueError:
            continue
        if filed < FILINGS_SINCE:
            continue
        items = [code.strip() for code in _at(columns["items"], index).split(",") if code.strip()]
        document = _at(columns["primaryDocument"], index)
        details: dict[str, Any] = {
            "accession": accession,
            "form": form,
            "url": filing_url(cik, accession, document),
        }
        report_date = _at(columns["reportDate"], index)
        if report_date:
            details["report_date"] = report_date
        if form == "8-K":
            details["items"] = items
            details["item_names"] = [item_name(code) for code in items]
        events.append(
            FilingEvent(
                kind=FILING_KINDS[form],
                event_date=filed,
                title=filing_title(form, items),
                accession=accession,
                details=details,
            )
        )
    return events


def filing_url(cik: str, accession: str, document: str) -> str:
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    return f"{folder}/{document}" if document else f"{folder}/"


def item_name(code: str) -> str:
    return EIGHT_K_ITEMS.get(code, f"Item {code}")


def filing_title(form: str, items: list[str]) -> str:
    if form != "8-K":
        return FILING_TITLES[form]
    substantive = [code for code in items if code != EXHIBITS_ITEM] or items
    if not substantive:
        return "Current report (8-K)"
    return f"{'; '.join(item_name(code) for code in substantive)} (8-K)"


def _at(values: list[Any], index: int) -> str:
    value = values[index] if index < len(values) else None
    return "" if value is None else str(value)
