"""The Alpaca market-clock lookup behind `/api/v1/status` and `/api/v1/market`
(system design §5). `None` when `ALPACA_KEY_ID`/`ALPACA_SECRET_KEY` are unset
(N4) -- `get_alpaca_client()` is the single place that check lives. The
underlying `GET /v2/clock` call is cached ~60s (`AlpacaClient.get_clock`),
shared with `quotes_poll`'s own clock check so the two never race to
refresh it independently.
"""

from __future__ import annotations

from stockticker.ingest.alpaca.client import get_alpaca_client
from stockticker.models.status import MarketClock


async def fetch_market_clock() -> MarketClock | None:
    client = get_alpaca_client()
    if client is None:
        return None
    return await client.get_clock()
