# Query plans: `/api/v1/market` and `/api/v1/listings/{symbol}/bars`

System design §5 requires `/api/v1/market` to stay under 300 ms (p95) at the
Load table's estimate of ~503 active Listings and ~1.1M `daily_bars` rows.
Measured against a seeded compose Postgres at that scale (503 Listings,
1,181,044 `daily_bars` rows, 1,181,044 `market_caps` rows spanning
2018-01-01 to today, `ANALYZE`d before measuring) using the exact query text
in `queries/market.py`/`queries/bars.py`:

## `/api/v1/market` (`queries/market.py::MARKET_QUERY`)

```
Nested Loop Left Join  (actual time=0.762..11.466 rows=503 loops=1)
  Buffers: shared hit=3485 read=557
  -> Nested Loop Left Join (listings x companies x quotes, then the previous
     Trading Day)  (actual time=0.732..5.992 rows=503 loops=1)
     -> Memoize (per-quote previous-Trading-Day lookup)
        -> Index Only Scan Backward using trading_days_pkey
           Index Cond: (trade_date < COALESCE(quote's NY date, CURRENT_DATE))
     -> Index Scan using daily_bars_pkey  (actual time=0.009..0.009 rows=1 loops=503)
        Index Cond: (symbol = l.symbol AND trade_date = <that previous Trading Day>)
  -> Limit (per-listing latest market_caps row)  (actual time=0.011..0.011 rows=1 loops=503)
     -> Index Scan Backward using market_caps_pkey
        Index Cond: (cik = l.cik AND trade_date <= CURRENT_DATE)
Planning Time: 2.743 ms
Execution Time: 11.599 ms
```

11.6 ms total — well under the 300 ms budget, with room to spare for slower
hardware than this laptop. Every step against `daily_bars`/`market_caps`
(the two ~1.18M-row tables) is an index lookup, never a sequential scan:
finding each Listing's previous Trading Day is an `Index Only Scan` against
the small (~2,300-row) `trading_days` table, and the exact `daily_bars` row
for that date is then a plain `Index Scan` on the table's own primary key
`(symbol, trade_date)` -- an equality lookup, not a range scan, which is
*more* index-friendly than the "just take the latest bar" version of this
query. `market_caps` gets the same `LATERAL` + `LIMIT 1` treatment against
its own `(cik, trade_date)` primary key. (The `Memoize` node here is an
artifact of the seed script giving every quote the same `observed_at`; with
distinct observed times per Listing, Postgres does 503 small index probes
instead of 1 cached one, still cheap against a 2,300-row index.)

## `/api/v1/listings/{symbol}/bars` (`queries/bars.py::_BARS_QUERY`)

Full default range (`2018-01-01` to today) for one symbol, against the same
~1.18M-row `daily_bars` table:

```
Sort  (actual time=13.517..13.636 rows=2348 loops=1)
  -> Bitmap Heap Scan on daily_bars  (actual time=0.570..12.992 rows=2348 loops=1)
     Recheck Cond: (symbol = 'PERF0250' AND trade_date >= '2018-01-01' AND trade_date <= CURRENT_DATE)
     -> Bitmap Index Scan on daily_bars_pkey
        Index Cond: (symbol = 'PERF0250' AND trade_date >= '2018-01-01' AND trade_date <= CURRENT_DATE)
Planning Time: 0.220 ms
Execution Time: 13.783 ms
```

13.8 ms — the `daily_bars` primary key `(symbol, trade_date)` already
covers this query exactly; no extra index was needed.

## Reproducing

```bash
docker compose up -d db migrate
docker compose exec -T db psql -U postgres -d stockticker < api/scripts/perf_seed.sql
docker compose exec db psql -U postgres -d stockticker -c "ANALYZE;"
docker compose exec db psql -U postgres -d stockticker \
  -c "EXPLAIN (ANALYZE, BUFFERS) <query from queries/market.py or queries/bars.py>"
```

`api/scripts/perf_seed.sql` (committed) inserts and the same file's header
comment gives the cleanup command -- this data is never part of the
committed test fixtures, which use much smaller, targeted datasets (see
`tests/integration/seed.py`).
