"""`BarSource` implementation over Alpaca `/v2/stocks/bars`
(system design §4, `bars_backfill`/`bars_daily`). `providers.BarSource`
wants fully joined bars back from one call; this adapter makes both
`adjustment` passes itself (`feed=sip`, full pagination each) and joins
them -- `close` from the `raw` pass, `adj_close` from the `all` pass's
`close` -- keeping only a (symbol, date) present in both."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from stockticker.ingest.alpaca.client import RawBar, RawBarsSource
from stockticker.ingest.common import ALPACA_SOURCE, FEED_SIP
from stockticker.ingest.providers import ProviderBar


def join_raw_bars(raw: dict[str, list[RawBar]], adjusted: dict[str, list[RawBar]]) -> list[ProviderBar]:
    joined: list[ProviderBar] = []
    for symbol, raw_bars in raw.items():
        raw_by_date = {bar.trade_date: bar for bar in raw_bars}
        adj_by_date = {bar.trade_date: bar for bar in adjusted.get(symbol, [])}
        for trade_date in sorted(raw_by_date.keys() & adj_by_date.keys()):
            raw_bar = raw_by_date[trade_date]
            joined.append(
                ProviderBar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=raw_bar.open,
                    high=raw_bar.high,
                    low=raw_bar.low,
                    close=raw_bar.close,
                    volume=raw_bar.volume,
                    adj_close=adj_by_date[trade_date].close,
                    source=ALPACA_SOURCE,
                )
            )
    return joined


class AlpacaBarSource:
    def __init__(self, client: RawBarsSource, *, feed: str = FEED_SIP) -> None:
        self._client = client
        self._feed = feed

    async def daily_bars(self, symbols: Sequence[str], start: date, end: date) -> list[ProviderBar]:
        raw = await self._client.get_bars(symbols, start, end, adjustment="raw", feed=self._feed)
        adjusted = await self._client.get_bars(symbols, start, end, adjustment="all", feed=self._feed)
        return join_raw_bars(raw, adjusted)
