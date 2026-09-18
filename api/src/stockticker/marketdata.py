"""Placeholder for the Alpaca market-clock client.

`/api/v1/status` needs `is_open`/`next_open`/`next_close` (system design §5),
but the Alpaca client itself is out of scope for the API foundation. This
function is the seam: it returns `None` today, and the agent building the
Alpaca ingest client (§4, `calendar_sync`/`quotes_poll`) replaces the body
with a real call to `GET /v2/clock`, cached ~60s per the design's own
`quotes_poll` note. Keep the name and return type stable — `status.py`
imports it directly.
"""

from __future__ import annotations

from stockticker.models.status import MarketClock


async def fetch_market_clock() -> MarketClock | None:
    return None
