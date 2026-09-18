"""Symbol normalization (system design §4).

The canonical form is the dot form (`BRK.B`), used everywhere in the schema
(`listings.symbol`, `daily_bars.symbol`, ...). Wikipedia and Alpaca already
use dots; SEC EDGAR uses dashes (`BRK-B`). This is the one place that
translates between them — every ingest job should call it on any symbol it
reads from a provider before writing or querying by it.
"""

from __future__ import annotations

import re

# Constituent List / Listing tickers: 1–5 letters, optional single-letter
# share class after a dot (`BRK.B`). Digits and longer junk (Wikipedia
# footnote IDs like `T131793`) are rejected before they become Listings.
LISTING_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def normalize_symbol(raw: str) -> str:
    """Return the canonical dot form of a ticker symbol.

    Trims whitespace, upper-cases, and converts a single dash-form share
    class separator (`BRK-B` -> `BRK.B`) to a dot. A symbol with no share
    class separator passes through unchanged.
    """
    cleaned = raw.strip().upper()
    if not cleaned:
        raise ValueError("symbol must not be empty")
    return cleaned.replace("-", ".")


def is_valid_listing_ticker(symbol: str) -> bool:
    """True when `symbol` is already in canonical form and matches the
    Constituent List ticker shape (issue #38)."""
    return bool(LISTING_TICKER_RE.fullmatch(symbol))
