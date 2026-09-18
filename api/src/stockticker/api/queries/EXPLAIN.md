# Query plans: `/api/v1/market` and `/api/v1/listings/{symbol}/bars`

System design §5 requires `/api/v1/market` to stay under 300 ms (p95) at the
Load table's estimate of ~503 active Listings and ~1.1M `daily_bars` rows.
Measured against a seeded compose Postgres at that scale (503 Listings,
1,181,044 `daily_bars` rows, 1,181,044 `market_caps` rows spanning
2018-01-01 to today, `ANALYZE`d before measuring) using the exact query text
in `queries/market.py`/`queries/bars.py`:

## `/api/v1/market` (`queries/market.py::MARKET_QUERY`)

```
Nested Loop Left Join  (actual time=0.902..15.671 rows=503 loops=1)
  Buffers: shared hit=4693 read=905
  -> Nested Loop Left Join (listings x companies x quotes, then the previous
     Trading Day's bar)  (actual time=0.866..7.646 rows=503 loops=1)
     -> Merge Left Join (listings x companies x quotes)  (actual time=0.547..0.844 rows=503 loops=1)
     -> Index Scan using daily_bars_pkey  (actual time=0.008..0.008 rows=1 loops=503)
        Index Cond: (symbol = l.symbol
          AND trade_date = prev_trading_day(COALESCE(quote's NY date, CURRENT_DATE)))
  -> Limit (per-listing latest market_caps row)  (actual time=0.016..0.016 rows=1 loops=503)
     -> Index Scan Backward using market_caps_pkey
        Index Cond: (cik = l.cik AND trade_date <= CURRENT_DATE)
Planning Time: 0.824 ms
Execution Time: 15.759 ms
```

15.8 ms total — well under the 300 ms budget, with room to spare for slower
hardware than this laptop. Every step against `daily_bars`/`market_caps`
(the two ~1.18M-row tables) is an index lookup, never a sequential scan:
`public.prev_trading_day` (migration 0001 -- DRY pass on #6's review gate,
replacing this query's own `trading_days` lookup) resolves the previous
Trading Day, and Postgres folds it straight into the `daily_bars_pkey`
index condition, so the exact bar for that date is a plain equality lookup
on the table's own primary key `(symbol, trade_date)` -- not a range scan,
which is _more_ index-friendly than the "just take the latest bar" version
of this query. `market_caps` gets the same `LATERAL` + `LIMIT 1` treatment
against its own `(cik, trade_date)` primary key (no shared function for
that one yet).

## `/api/v1/listings/{symbol}/bars` (`queries/bars.py::_BARS_QUERY`)

Full default range (`2018-01-01` to today) for one symbol, against the same
~1.18M-row `daily_bars` table:

```
Sort  (actual time=14.666..14.780 rows=2348 loops=1)
  -> Bitmap Heap Scan on daily_bars  (actual time=0.629..14.089 rows=2348 loops=1)
     Recheck Cond: (symbol = 'PERF0250' AND trade_date >= '2018-01-01' AND trade_date <= CURRENT_DATE)
     -> Bitmap Index Scan on daily_bars_pkey
        Index Cond: (symbol = 'PERF0250' AND trade_date >= '2018-01-01' AND trade_date <= CURRENT_DATE)
Planning Time: 0.211 ms
Execution Time: 14.926 ms
```

14.9 ms — the `daily_bars` primary key `(symbol, trade_date)` already
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
