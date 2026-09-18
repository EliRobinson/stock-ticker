from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import create_async_engine

from stockticker.ingest.http import reset_rate_budgets
from stockticker.ingest.wikipedia.parser import MIN_ROWS, ConstituentsParseError, parse_constituents
from stockticker.ingest.wikipedia.sync import USER_AGENT, WIKIPEDIA_URL, run_constituents_sync

FIXTURES = Path(__file__).parent.parent / "fixtures" / "wikipedia"
NORMAL_PAGE = (FIXTURES / "sp500_constituents.html").read_text()
MALFORMED_PAGE = (FIXTURES / "sp500_malformed.html").read_text()


@pytest.fixture(autouse=True)
def _reset_budgets() -> Iterator[None]:
    reset_rate_budgets()
    yield
    reset_rate_budgets()


def _truncated_page(keep_rows: int) -> str:
    head, _, rest = NORMAL_PAGE.partition("<tr>\n<td>")
    rows = ("<tr>\n<td>" + rest).split("</tr>")
    return head + "</tr>".join(rows[:keep_rows]) + "</tr></tbody></table></body></html>"


def test_normal_page_parses_every_constituent() -> None:
    parsed = parse_constituents(NORMAL_PAGE)

    assert len(parsed.rows) == 503
    assert parsed.rejected == ()
    assert len({row.symbol for row in parsed.rows}) == 503
    assert all(len(row.cik) == 10 and row.cik.isdigit() for row in parsed.rows)
    assert all(row.name and row.sector for row in parsed.rows)


def test_first_row_matches_the_page() -> None:
    mmm = parse_constituents(NORMAL_PAGE).rows[0]

    assert mmm.symbol == "MMM"
    assert mmm.name == "3M"
    assert mmm.sector == "Industrials"
    assert mmm.sub_industry == "Industrial Conglomerates"
    assert mmm.headquarters == "Saint Paul, Minnesota"
    assert mmm.date_added == date(1957, 3, 4)
    assert mmm.cik == "0000066740"


def test_share_classes_keep_the_dot_form_and_one_cik() -> None:
    by_symbol = {row.symbol: row for row in parse_constituents(NORMAL_PAGE).rows}

    assert by_symbol["BRK.B"].cik == "0001067983"
    assert by_symbol["BF.B"].name == "Brown–Forman"
    assert by_symbol["GOOGL"].cik == by_symbol["GOOG"].cik == "0001652044"
    assert by_symbol["GOOGL"].name == by_symbol["GOOG"].name == "Alphabet Inc."
    assert by_symbol["FOXA"].cik == by_symbol["FOX"].cik
    assert by_symbol["NWSA"].cik == by_symbol["NWS"].cik


def test_headquarters_keeps_the_text_around_links() -> None:
    by_symbol = {row.symbol: row for row in parse_constituents(NORMAL_PAGE).rows}

    assert by_symbol["AOS"].headquarters == "Milwaukee, Wisconsin"


def test_footnote_markers_are_dropped() -> None:
    rows = parse_constituents(NORMAL_PAGE).rows

    assert not any("[" in f"{row.name}{row.sector}{row.sub_industry}{row.headquarters}" for row in rows)


def test_malformed_page_names_the_missing_columns() -> None:
    with pytest.raises(ConstituentsParseError, match="missing columns: Symbol, CIK"):
        parse_constituents(MALFORMED_PAGE)


def test_page_without_the_table_fails() -> None:
    with pytest.raises(ConstituentsParseError, match="no table"):
        parse_constituents("<html><body><table id='other'></table></body></html>")


def test_fewer_than_480_rows_fails() -> None:
    page = _truncated_page(MIN_ROWS - 1)

    with pytest.raises(ConstituentsParseError, match=f"only {MIN_ROWS - 1} rows"):
        parse_constituents(page)


def test_exactly_480_rows_passes() -> None:
    assert len(parse_constituents(_truncated_page(MIN_ROWS)).rows) == MIN_ROWS


def test_a_non_numeric_cik_fails() -> None:
    page = NORMAL_PAGE.replace("<td>0000066740</td>", "<td>n/a</td>", 1)

    with pytest.raises(ConstituentsParseError, match=r"\(MMM\): bad CIK 'n/a'"):
        parse_constituents(page)


@pytest.mark.parametrize("cik", ["١٢٣", "12345678901", "0x1F", "1 23"])
def test_a_cik_must_be_one_to_ten_ascii_digits(cik: str) -> None:
    page = NORMAL_PAGE.replace("<td>0000066740</td>", f"<td>{cik}</td>", 1)

    with pytest.raises(ConstituentsParseError, match="bad CIK"):
        parse_constituents(page)


@pytest.mark.parametrize(
    "junk",
    [
        "T131793",
        "T137FB9",
        "T3F04A1",
        "BRK.BB",
        "TOOLONG",
        "AAPL1",
    ],
)
def test_invalid_tickers_are_rejected_as_failed_items_not_a_failed_parse(junk: str) -> None:
    page = NORMAL_PAGE.replace(">MMM</a>", f">{junk}</a>", 1)

    parsed = parse_constituents(page)

    assert junk not in {row.symbol for row in parsed.rows}
    assert len(parsed.rejected) == 1
    assert parsed.rejected[0].key == junk
    assert "invalid ticker" in parsed.rejected[0].error


@respx.mock
async def test_malformed_page_fails_the_run_before_touching_the_db() -> None:
    route = respx.get(WIKIPEDIA_URL).mock(return_value=httpx.Response(200, text=MALFORMED_PAGE))
    unreachable = create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:1/none")

    with pytest.raises(ConstituentsParseError):
        await run_constituents_sync(unreachable)

    assert route.call_count == 1
    assert route.calls[0].request.headers["User-Agent"] == USER_AGENT
    await unreachable.dispose()


def test_the_wikipedia_user_agent_names_no_operator() -> None:
    assert "@" not in USER_AGENT
