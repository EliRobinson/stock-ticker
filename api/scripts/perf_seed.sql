-- Seeds ~503 Listings x ~2,270 Trading Days (~1.1M daily_bars/market_caps
-- rows) against the compose Postgres, matching system design §5's Load
-- table, so /api/v1/market and /api/v1/listings/{symbol}/bars can be
-- EXPLAIN ANALYZE'd at realistic scale (see queries/EXPLAIN.md).
--
-- Usage:
--   docker compose up -d db migrate
--   docker compose exec -T db psql -U postgres -d stockticker < api/scripts/perf_seed.sql
--   docker compose exec db psql -U postgres -d stockticker -c "ANALYZE;"
--   docker compose exec db psql -U postgres -d stockticker \
--     -c "EXPLAIN (ANALYZE, BUFFERS) <query from queries/market.py or queries/bars.py>"
--
-- Cleanup (this data is never part of the committed test fixtures):
--   docker compose exec db psql -U postgres -d stockticker -c "
--     DELETE FROM daily_bars WHERE symbol LIKE 'PERF%';
--     DELETE FROM quotes WHERE symbol LIKE 'PERF%';
--     DELETE FROM market_caps WHERE cik LIKE '8%';
--     DELETE FROM listings WHERE symbol LIKE 'PERF%';
--     DELETE FROM companies WHERE cik LIKE '8%';
--     DELETE FROM trading_days WHERE trade_date >= date '2018-01-01';"

\timing on

INSERT INTO trading_days (trade_date, open_at, close_at)
SELECT d,
       (d + time '09:30') AT TIME ZONE 'America/New_York',
       (d + time '16:00') AT TIME ZONE 'America/New_York'
FROM generate_series('2018-01-01'::date, CURRENT_DATE, interval '1 day') AS d
WHERE extract(isodow from d) < 6
ON CONFLICT (trade_date) DO NOTHING;

INSERT INTO companies (cik, name, sector, is_active)
SELECT lpad((8000000000 + n)::text, 10, '0'), 'Perf Test Co ' || n, 'Technology', true
FROM generate_series(1, 503) AS n
ON CONFLICT (cik) DO NOTHING;

INSERT INTO listings (symbol, cik, is_primary, is_active, first_bar_date)
SELECT 'PERF' || lpad(n::text, 4, '0'), lpad((8000000000 + n)::text, 10, '0'), true, true, date '2018-01-01'
FROM generate_series(1, 503) AS n
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO daily_bars (symbol, trade_date, open, high, low, close, volume, adj_close, source, ingested_at)
SELECT
  l.symbol,
  td.trade_date,
  100 + ((td.trade_date - date '2018-01-01') % 50),
  105 + ((td.trade_date - date '2018-01-01') % 50),
  95 + ((td.trade_date - date '2018-01-01') % 50),
  100 + ((td.trade_date - date '2018-01-01') % 50),
  1000000,
  100 + ((td.trade_date - date '2018-01-01') % 50),
  'perf-seed',
  now()
FROM listings l
CROSS JOIN trading_days td
WHERE l.symbol LIKE 'PERF%'
ON CONFLICT (symbol, trade_date) DO NOTHING;

INSERT INTO quotes (symbol, price, observed_at, fetched_at, feed)
SELECT symbol, 110, now(), now(), 'iex' FROM listings WHERE symbol LIKE 'PERF%'
ON CONFLICT (symbol) DO UPDATE SET price = excluded.price, observed_at = excluded.observed_at,
  fetched_at = excluded.fetched_at;

INSERT INTO market_caps (cik, trade_date, market_cap, shares_used, shares_as_of, is_multi_class)
SELECT l.cik, td.trade_date, 1000000000, 10000000, td.trade_date, false
FROM listings l
CROSS JOIN trading_days td
WHERE l.symbol LIKE 'PERF%'
ON CONFLICT (cik, trade_date) DO NOTHING;

SELECT 'companies' AS table_name, count(*) FROM companies WHERE cik LIKE '8%'
UNION ALL SELECT 'listings', count(*) FROM listings WHERE symbol LIKE 'PERF%'
UNION ALL SELECT 'trading_days', count(*) FROM trading_days
UNION ALL SELECT 'daily_bars', count(*) FROM daily_bars WHERE symbol LIKE 'PERF%'
UNION ALL SELECT 'market_caps', count(*) FROM market_caps WHERE cik LIKE '8%'
UNION ALL SELECT 'quotes', count(*) FROM quotes WHERE symbol LIKE 'PERF%';
