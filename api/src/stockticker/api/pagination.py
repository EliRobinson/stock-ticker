"""Keyset pagination shared by `/events` and `/notes` (system design §5,
amended: "`/notes` and `/events` use cursor pagination (`limit`,
`next_cursor`)").

A cursor is the base64url encoding of a small JSON object naming the last
row's sort-key values, e.g. `{"event_date": "2024-01-01", "id": 42}`. It is
opaque to the client -- never parsed except by `decode_cursor` here -- so
the sort key it encodes can change without breaking a client that just
echoes the `next_cursor` it was given back on the next request.

`Page[T]` and `paginate()` are the one place a router decides whether
there's a next page: the query is always asked for `limit + 1` rows, so an
exact-limit result can tell "that's everything" apart from "there's more"
without a second round trip or an off-by-one (a naive `len(items) ==
limit` check gets this wrong on a last page that happens to be exactly
`limit` long).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from stockticker.api.problems import Problem
from stockticker.models.pagination import Page

DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000

# events.id is bigserial (int8); notes' keyset also carries small ints once
# decoded. A cursor value outside this range can never match a real row, and
# handing it to asyncpg as a bigint bind param raises rather than just
# finding nothing -- reject it as a bad cursor instead of a 500.
BIGINT_MIN = -(2**63)
BIGINT_MAX = 2**63 - 1

__all__ = [
    "BIGINT_MAX",
    "BIGINT_MIN",
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "Page",
    "cursor_bigint",
    "cursor_date",
    "cursor_uuid",
    "decode_cursor",
    "encode_cursor",
    "paginate",
]


def _bad_cursor() -> Problem:
    """`raise _bad_cursor()` or `raise _bad_cursor() from exc` -- every
    invalid-cursor case (a decode failure, a missing key, a wrong-typed or
    out-of-range value) is the same client-facing 422, so every call site
    shares this one message instead of retyping it."""
    return Problem("invalid-cursor", 422, "cursor is not a valid page token")


def paginate[T](
    rows: Sequence[T], *, limit: int, cursor_of: Callable[[T], dict[str, Any]]
) -> tuple[list[T], str | None]:
    """`rows` must be the result of a query for `limit + 1` rows, ordered by
    the same key `cursor_of` reads. Trims back to `limit` and encodes the
    cursor only when the extra row proves there's more."""
    has_more = len(rows) > limit
    items = list(rows[:limit])
    next_cursor = encode_cursor(cursor_of(items[-1])) if has_more and items else None
    return items, next_cursor


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        decoded = json.loads(raw)
    except (binascii.Error, json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        raise _bad_cursor() from exc
    if not isinstance(decoded, dict):
        raise _bad_cursor()
    return decoded


def cursor_bigint(decoded: dict[str, Any], key: str) -> int:
    """A cursor field that must be a Postgres `bigint`: rejects `null`, a
    list, a float, or anything else `int()` would silently coerce or choke
    on with a `TypeError` rather than a `ValueError` (a bare `int(x)` call
    only catches the latter) -- and rejects a value out of `bigint` range
    before it ever reaches asyncpg."""
    value = decoded.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _bad_cursor()
    if not (BIGINT_MIN <= value <= BIGINT_MAX):
        raise _bad_cursor()
    return value


def cursor_date(decoded: dict[str, Any], key: str) -> date:
    value = decoded.get(key)
    if not isinstance(value, str):
        raise _bad_cursor()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _bad_cursor() from exc


def cursor_uuid(decoded: dict[str, Any], key: str) -> UUID:
    value = decoded.get(key)
    if not isinstance(value, str):
        raise _bad_cursor()
    try:
        return UUID(value)
    except ValueError as exc:
        raise _bad_cursor() from exc


def cursor_str(decoded: dict[str, Any], key: str) -> str:
    value = decoded.get(key)
    if not isinstance(value, str) or not value:
        raise Problem("invalid-cursor", 422, "cursor is not a valid page token")
    return value
