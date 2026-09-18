"""`QuoteSource` implementation over Alpaca `/v2/stocks/snapshots`
(system design §4, `quotes_poll`). A symbol with no `latestTrade` in the
response is simply absent from the result -- the protocol's contract."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from stockticker.ingest.alpaca.client import SnapshotsSource
from stockticker.ingest.common import FEED_IEX
from stockticker.ingest.providers import ProviderQuote


class AlpacaQuoteSource:
    def __init__(self, client: SnapshotsSource, *, feed: str = FEED_IEX) -> None:
        self._client = client
        self._feed = feed

    async def snapshot(self, symbols: Sequence[str]) -> list[ProviderQuote]:
        """No retries (system design §4: "No retries, because the next tick
        is the retry") -- a batch that errors is the caller's problem to
        record as failed items, not this method's to mask with a retry."""
        return await self._client.get_snapshots(symbols, feed=self._feed, attempts=1)

    def stream(self, symbols: Sequence[str]) -> AsyncIterator[ProviderQuote]:
        """The paid-SIP-websocket upgrade path (system design §9/§10) --
        free-tier Alpaca has no push feed, so this satisfies
        `providers.QuoteSource` without implementing it."""
        raise NotImplementedError("Alpaca free-tier quotes are poll-only; see QuoteSource.snapshot")
