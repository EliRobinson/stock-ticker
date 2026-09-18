# Alpaca and SEC EDGAR as free data sources

We need live Quotes for ~500 Companies, Daily Bars back to 2018, and real historical Market Cap, all at no cost, built inside a 4-hour window. As of 2026-09-17, only Alpaca's free tier covers both live Quotes (batched multi-symbol snapshots, 200 calls/min) and deep history (all-exchange SIP bars since 2016). No free price source gives historical shares outstanding, so we take them from SEC EDGAR's companyfacts API and compute Market Cap ourselves.

## Consequences

- Free Alpaca Quotes are real-time but come from the IEX exchange alone, so they can differ slightly from the consolidated price. The upgrade path is Alpaca's paid tier (full SIP in real time). It uses the same endpoints with `feed=sip`, so no other code changes.
- Market Cap moves in quarterly steps, because EDGAR shares outstanding are reported once per filing. We must adjust for stock splits between a filing and a trading day ourselves.
- Running the app needs a free Alpaca API key. EDGAR needs no key, only a User-Agent header with a contact email.

## Considered Options

- **yfinance**: no key needed, but it is unofficial, its terms say "personal use only", its delay and rate limits are undocumented, and it gives only today's share count.
- **Finnhub, Tiingo, Twelve Data, Massive (Polygon)**: on the free tiers, each one fails on at least one need. The problems are one symbol per call, too little history, end-of-day data only, or an "internal use only" licence.
- **Morningstar**: no free public API.
