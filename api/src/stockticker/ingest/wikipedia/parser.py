"""Parse the "List of S&P 500 companies" constituents table.

selectolax, not `pandas.read_html`: this is one eight-column table, of
which seven columns are read, and selectolax is a single small wheel with no transitive
dependencies. `read_html` would pull in pandas, numpy, and lxml or
bs4/html5lib (~60 MB) to produce a DataFrame we would immediately turn back
into rows, and its type coercion would strip the CIK's leading zeros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from selectolax.parser import HTMLParser, Node

from stockticker.ingest.symbols import normalize_cik, normalize_symbol

MIN_ROWS = 480

# Header text -> field. Matching is on the header's visible text, so a
# column reorder is harmless and a renamed or dropped column fails loudly.
EXPECTED_COLUMNS: dict[str, str] = {
    "Symbol": "symbol",
    "Security": "security",
    "GICS Sector": "sector",
    "GICS Sub-Industry": "sub_industry",
    "Headquarters Location": "headquarters",
    "Date added": "date_added",
    "CIK": "cik",
}

_CLASS_SUFFIX = re.compile(r"\s*\((?:Class|Series) [A-Z]\)\s*$")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# ASCII only: str.isdigit() and \d both accept other scripts' digits.
_CIK = re.compile(r"[0-9]{1,10}")


class ConstituentsParseError(Exception):
    """The page no longer looks like the table we know. The run fails and
    the last good list stays in place."""


@dataclass(frozen=True, slots=True)
class ConstituentRow:
    symbol: str
    name: str
    sector: str
    sub_industry: str | None
    headquarters: str | None
    date_added: date | None
    cik: str


def parse_constituents(html: str) -> list[ConstituentRow]:
    tree = HTMLParser(html)
    table = tree.css_first("table#constituents")
    if table is None:
        raise ConstituentsParseError("no table with id 'constituents'")

    rows = table.css("tr")
    if not rows:
        raise ConstituentsParseError("constituents table has no rows")

    headers = [_cell_text(cell) for cell in rows[0].css("th")]
    positions = {text: index for index, text in enumerate(headers)}
    missing = [column for column in EXPECTED_COLUMNS if column not in positions]
    if missing:
        raise ConstituentsParseError(f"missing columns: {', '.join(missing)}")
    index_of = {field: positions[column] for column, field in EXPECTED_COLUMNS.items()}

    parsed: list[ConstituentRow] = []
    for row_number, row in enumerate(rows[1:], start=2):
        cells = [_cell_text(cell) for cell in row.css("td")]
        if len(cells) < len(headers):
            raise ConstituentsParseError(f"row {row_number} has {len(cells)} cells, expected {len(headers)}")
        parsed.append(_to_row(cells, index_of, row_number))

    if len(parsed) < MIN_ROWS:
        raise ConstituentsParseError(f"only {len(parsed)} rows, expected at least {MIN_ROWS}")
    return parsed


def _to_row(cells: list[str], index_of: dict[str, int], row_number: int) -> ConstituentRow:
    def field(name: str) -> str:
        return cells[index_of[name]]

    try:
        symbol = normalize_symbol(field("symbol"))
    except ValueError as exc:
        raise ConstituentsParseError(f"row {row_number}: empty symbol") from exc

    cik_raw = field("cik")
    if not _CIK.fullmatch(cik_raw):
        raise ConstituentsParseError(f"row {row_number} ({symbol}): bad CIK {cik_raw!r}")

    name = _CLASS_SUFFIX.sub("", field("security"))
    sector = field("sector")
    if not name or not sector:
        raise ConstituentsParseError(f"row {row_number} ({symbol}): empty name or sector")

    date_match = _ISO_DATE.search(field("date_added"))
    return ConstituentRow(
        symbol=symbol,
        name=name,
        sector=sector,
        sub_industry=field("sub_industry") or None,
        headquarters=field("headquarters") or None,
        date_added=date.fromisoformat(date_match.group(0)) if date_match else None,
        cik=normalize_cik(cik_raw),
    )


def _cell_text(cell: Node) -> str:
    for footnote in cell.css("sup"):
        footnote.decompose()
    return " ".join(cell.text(deep=True).split())
