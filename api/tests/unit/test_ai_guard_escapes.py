"""SQL guard cases from the review round: identifier folding, schema pinning,
string amplifiers, and every read-only escape the foundation review proved
`ai_reader` can reach on its own (so the guard has to stop them)."""

from __future__ import annotations

import pytest

from stockticker.ai.guard import GuardError, guard_sql


def rejected(sql: str) -> str:
    with pytest.raises(GuardError) as caught:
        guard_sql(sql)
    return str(caught.value)


@pytest.mark.parametrize(
    "sql",
    [
        'WITH "Pg_Settings" AS (SELECT 1) SELECT * FROM pg_settings',
        'WITH "PG_AUTHID" AS (SELECT 1 AS a) SELECT * FROM pg_authid',
        'WITH "Pg_Class" AS (SELECT 1) SELECT relname FROM pg_class',
        'WITH PG_STAT_ACTIVITY AS (SELECT 1) SELECT * FROM "PG_STAT_ACTIVITY"',
        'WITH "Companies" AS (SELECT 1) SELECT * FROM public.companies',
    ],
)
def test_cte_names_compare_the_way_postgres_folds_identifiers(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT * FROM "COMPANIES"',
        'SELECT * FROM "Companies"',
        'SELECT * FROM "AI".companies',
        'SELECT * FROM "Ai"."companies"',
    ],
)
def test_quoted_names_are_exact(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ('WITH "Q" AS (SELECT 1 AS a) SELECT * FROM "Q"', 'WITH "Q" AS (SELECT 1 AS a) SELECT * FROM "Q"'),
        ("WITH q AS (SELECT 1 AS a) SELECT * FROM Q", "WITH q AS (SELECT 1 AS a) SELECT * FROM Q"),
        (
            'WITH pg_class AS (SELECT 1 AS a) SELECT * FROM "pg_class"',
            'WITH pg_class AS (SELECT 1 AS a) SELECT * FROM "pg_class"',
        ),
    ],
)
def test_ctes_match_under_postgres_folding(sql: str, expected: str) -> None:
    assert guard_sql(sql).sql == expected


@pytest.mark.parametrize(
    ("sql", "pinned"),
    [
        ("SELECT name FROM companies", "SELECT name FROM ai.companies"),
        ("SELECT name FROM Companies", "SELECT name FROM ai.Companies"),
        (
            "SELECT c.name FROM companies c JOIN listings l ON l.cik = c.cik",
            "SELECT c.name FROM ai.companies AS c JOIN ai.listings AS l ON l.cik = c.cik",
        ),
        (
            "WITH companies AS (SELECT cik FROM companies) SELECT * FROM companies",
            "WITH companies AS (SELECT cik FROM ai.companies) SELECT * FROM companies",
        ),
    ],
)
def test_bare_view_names_are_pinned_to_the_ai_schema(sql: str, pinned: str) -> None:
    assert guard_sql(sql).sql == pinned


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT repeat('x', 200000000) FROM generate_series(1, 20)",
        "SELECT lpad('x', 200000000, 'y')",
        "SELECT rpad('x', 200000000)",
    ],
)
def test_rejects_string_amplifiers(sql: str) -> None:
    rejected(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SET default_transaction_read_only = off",
        "SET SESSION default_transaction_read_only = off",
        "SET LOCAL statement_timeout = 0",
        "SET statement_timeout = 0",
        "SET work_mem = '2GB'",
        "SET LOCAL work_mem = '2GB'",
        "SET TRANSACTION READ WRITE",
        "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE",
        "RESET default_transaction_read_only",
        "RESET ALL",
        "BEGIN READ WRITE",
        "BEGIN; SELECT lo_from_bytea(0, 'x'); COMMIT",
        "SET default_transaction_read_only = off; BEGIN READ WRITE; SELECT lo_from_bytea(0, 'x')",
        "SELECT lo_from_bytea(0, 'x')",
        "SELECT lo_create(0)",
        "SELECT lo_open(1, 131072)",
        "SELECT lowrite(0, 'x')",
        "SELECT loread(0, 10)",
        "SELECT lo_unlink(1)",
        "SELECT lo_put(1, 0, 'x')",
        "SELECT lo_get(1)",
        "SELECT set_config('default_transaction_read_only', 'off', false)",
        "SELECT set_config('work_mem', '2GB', true)",
        "SELECT current_setting('work_mem')",
        "SELECT * FROM ai.companies WHERE set_config('statement_timeout', '0', true) IS NOT NULL",
    ],
)
def test_rejects_every_read_only_escape_from_the_foundation_review(sql: str) -> None:
    rejected(sql)
