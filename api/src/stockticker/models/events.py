from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from stockticker.models.pagination import Page

EventKind = Literal[
    "split",
    "reverse_split",
    "cash_dividend",
    "symbol_change",
    "spin_off",
    "filing_10k",
    "filing_10q",
    "filing_8k",
    "index_added",
]


class Event(BaseModel):
    id: int
    cik: str
    symbol: str | None
    event_date: date
    kind: EventKind
    title: str
    details: dict[str, Any]
    source: str
    source_ref: str


class EventsPage(Page[Event]):
    """Keyset page of Events (system design §5, amended). A distinct
    subclass, not a bare `Page[Event]` alias, so the OpenAPI schema keeps
    the name `EventsPage` instead of a generic-mangled one."""
