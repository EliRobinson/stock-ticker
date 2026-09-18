"""Small input guards shared by the read/Notes routers.

Postgres `text` columns reject an embedded NUL byte (`\\x00`) with a raw
`DataError` -- without a check here that surfaces as an unhandled 500
instead of a 422, for a value that was never going to match anything
anyway. `cik`/`symbol` also get a generous length cap: a CIK is 10 digits
and a symbol is a handful of characters, so an absurdly long value is
always a client error, not something worth a round trip to the DB to
reject.
"""

from __future__ import annotations

import re

from stockticker.api.problems import Problem

MAX_SYMBOL_LENGTH = 10

# CONTEXT.md: "SEC Central Index Key, 10-digit zero-padded string." Client
# input isn't required to be zero-padded, just numeric and no longer than
# the real thing.
_CIK_PATTERN = re.compile(r"^\d{1,10}$")


def reject_nul(value: str, *, field: str) -> str:
    if "\x00" in value:
        raise Problem("invalid-input", 422, f"{field} must not contain a NUL byte")
    return value


def clean_cik(value: str | None) -> str | None:
    if value is None:
        return None
    reject_nul(value, field="cik")
    if not _CIK_PATTERN.match(value):
        raise Problem("invalid-input", 422, "cik must be 1-10 digits")
    return value


def clean_symbol(value: str | None) -> str | None:
    if value is None:
        return None
    reject_nul(value, field="symbol")
    if len(value) > MAX_SYMBOL_LENGTH:
        raise Problem("invalid-input", 422, f"symbol must be at most {MAX_SYMBOL_LENGTH} characters")
    return value
