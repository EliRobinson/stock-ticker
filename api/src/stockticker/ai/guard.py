"""The SQL guard for `run_sql` (system design §6, "SQL guard").

The `ai_reader` role is the real security wall. The guard exists to catch
mistakes early with an error the model can act on, and to shrink what reaches
the database to plain `SELECT`s over the `ai` views.

The SQL that runs is regenerated from the parsed tree, never the model's
original text. That closes parser differentials (for example Postgres's
nested block comments, which another parser could read differently): what was
checked is exactly what executes.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MAX_SQL_CHARS = 20_000
ROW_LIMIT = 5_000

AI_SCHEMA = "ai"
AI_VIEWS = frozenset(
    {"companies", "listings", "trading_days", "daily_prices", "market_caps", "events", "notes", "quotes"}
)
AI_FUNCTIONS = frozenset({"returns_between", "today_ny"})

# Names as sqlglot reports them: an unknown function keeps its Postgres name,
# a known one reports sqlglot's canonical name (both lowercased here).
# Anything not listed is rejected.
_AGGREGATE = {
    "count", "sum", "avg", "min", "max", "stddev", "stddev_pop", "stddev_samp", "variance",
    "var_pop", "var_samp", "corr", "covar_pop", "covar_samp", "regr_slope", "regr_intercept",
    "regr_r2", "regr_count", "percentile_cont", "percentile_disc", "mode", "bool_and", "bool_or",
    "every", "array_agg", "string_agg", "group_concat", "count_if", "logical_and", "logical_or",
}  # fmt: skip
_WINDOW = {
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
}  # fmt: skip
_MATH = {
    "abs", "ceil", "ceiling", "floor", "round", "trunc", "sign", "sqrt", "cbrt", "power", "pow",
    "exp", "ln", "log", "log10", "log2", "mod", "div", "width_bucket", "safe_divide", "pi",
}  # fmt: skip
_DATE_TIME = {
    "now", "current_date", "current_timestamp", "current_time", "localtimestamp", "localtime",
    "date_trunc", "timestamp_trunc", "date_part", "extract", "age", "make_date", "make_interval",
    "make_timestamp", "make_timestamptz", "to_char", "time_to_str", "to_date", "str_to_date",
    "to_timestamp", "str_to_time", "unix_to_time", "date_bin", "justify_days", "justify_hours",
    "justify_interval", "isfinite", "timezone", "date_add", "date_sub", "date_diff", "ts_or_ds_to_date",
    "generate_series", "exploding_generate_series", "generate_date_array", "date", "to_number",
}  # fmt: skip
_STRING = {
    "lower", "upper", "initcap", "length", "char_length", "character_length", "substring", "substr",
    "left", "right", "trim", "btrim", "ltrim", "rtrim", "concat", "concat_ws", "dpipe", "replace",
    "split_part", "position", "str_position", "strpos", "starts_with", "startswith", "lpad", "rpad",
    "pad", "format", "reverse", "repeat", "regexp_replace", "regexp_like", "regexp_i_like",
    "regexp_extract", "regexp_match", "translate", "md5", "chr", "ascii", "quote_literal",
}  # fmt: skip
_CONDITIONAL = {"coalesce", "nullif", "greatest", "least", "case", "if", "iff"}
_CASTS = {"cast", "try_cast"}
_ARRAY_JSON = {
    "array", "unnest", "explode", "array_length", "array_size", "cardinality", "array_to_string",
    "array_join", "json_extract", "json_extract_scalar", "jsonb_extract", "jsonb_extract_scalar",
    "jsonb_extract_path_text", "json_extract_path_text", "jsonb_array_elements", "jsonb_each_text",
    "jsonb_typeof", "jsonb_array_length", "to_json", "to_jsonb", "row_to_json", "json_agg",
    "jsonb_agg", "json_build_object", "jsonb_build_object", "json_object", "json_format",
}  # fmt: skip
# Boolean connectives and a few predicates are `Func` nodes in sqlglot's tree.
_SYNTAX = {"and", "or", "xor", "not", "exists", "any", "all", "in", "struct", "paren"}

ALLOWED_FUNCTIONS = frozenset(
    _AGGREGATE | _WINDOW | _MATH | _DATE_TIME | _STRING | _CONDITIONAL | _CASTS | _ARRAY_JSON | _SYNTAX
)

_ALLOWED_CAST_TYPES = frozenset(
    {
        exp.DataType.Type.SMALLINT,
        exp.DataType.Type.INT,
        exp.DataType.Type.BIGINT,
        exp.DataType.Type.DECIMAL,
        exp.DataType.Type.FLOAT,
        exp.DataType.Type.DOUBLE,
        exp.DataType.Type.TEXT,
        exp.DataType.Type.VARCHAR,
        exp.DataType.Type.CHAR,
        exp.DataType.Type.DATE,
        exp.DataType.Type.TIME,
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.INTERVAL,
        exp.DataType.Type.BOOLEAN,
        exp.DataType.Type.JSON,
        exp.DataType.Type.JSONB,
        exp.DataType.Type.ARRAY,
    }
)

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Into",
        "Lock",
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Copy",
        "Set",
        "SetItem",
        "Transaction",
        "Commit",
        "Rollback",
        "TruncateTable",
        "Grant",
        "Revoke",
        "Use",
        "Describe",
        "Pragma",
        "Analyze",
        "Refresh",
        "LoadData",
        "Cache",
        "Uncache",
        "Kill",
        "Comment",
        "Summarize",
        "Declare",
        "Execute",
        "Show",
    )  # fmt: skip
    if hasattr(exp, name)
)


class GuardError(ValueError):
    """The query was rejected. The message is written for the model to read and act on."""


@dataclass(frozen=True)
class GuardedQuery:
    sql: str
    """The regenerated query, as checked."""
    wrapped_sql: str
    """`sql` wrapped with the row cap. This is what runs."""


def guard_sql(sql: str, *, ai_views: frozenset[str] = AI_VIEWS) -> GuardedQuery:
    if len(sql) > MAX_SQL_CHARS:
        raise GuardError(
            f"Query is {len(sql)} characters; the limit is {MAX_SQL_CHARS}. Write a shorter query."
        )
    if not sql.strip():
        raise GuardError("Query is empty.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (SqlglotError, RecursionError) as error:
        raise GuardError(f"Could not parse the query: {_first_line(error)}") from None

    if len(statements) != 1:
        raise GuardError(f"Send exactly one SELECT statement; this has {len(statements)}.")
    (statement,) = statements

    _check_top_level(statement)
    for node in statement.walk():
        _check_node(node, ai_views)

    try:
        checked = statement.sql(dialect="postgres", comments=False)
    except (SqlglotError, RecursionError) as error:
        raise GuardError(f"Could not rewrite the query: {_first_line(error)}") from None
    return GuardedQuery(sql=checked, wrapped_sql=f"SELECT * FROM ({checked}) AS q LIMIT {ROW_LIMIT + 1}")


def _check_top_level(statement: exp.Expr) -> None:
    query = statement.this if isinstance(statement, exp.Subquery) else statement
    if not isinstance(query, exp.Select | exp.SetOperation):
        kind = query.key.upper() if isinstance(query, exp.Expression) else type(query).__name__
        raise GuardError(f"Only SELECT (or WITH ... SELECT) is allowed; got {kind}.")


def _check_node(node: exp.Expr, ai_views: frozenset[str]) -> None:
    if isinstance(node, exp.Into):
        raise GuardError("SELECT ... INTO is not allowed. Return rows instead.")
    if isinstance(node, exp.Lock):
        raise GuardError("Locking clauses (FOR UPDATE / FOR SHARE) are not allowed.")
    if isinstance(node, _FORBIDDEN_NODES):
        raise GuardError(f"{node.key.upper()} is not allowed. Only SELECT queries can run.")
    if isinstance(node, exp.Table):
        _check_table(node, ai_views)
    elif isinstance(node, exp.Func):
        _check_function(node)
    elif isinstance(node, exp.DataType) and isinstance(node.parent, exp.Cast | exp.TryCast):
        _check_cast_type(node)


def _check_table(table: exp.Table, ai_views: frozenset[str]) -> None:
    if table.catalog:
        raise GuardError(f"Cross-database references are not allowed: {table.sql(dialect='postgres')}.")
    schema = table.db.lower() if table.db else ""
    if schema and schema != AI_SCHEMA:
        raise GuardError(
            f"Schema '{table.db}' is not readable. Only the ai views are: "
            f"{', '.join(sorted(f'ai.{v}' for v in ai_views))}."
        )
    if isinstance(table.this, exp.Func):
        return  # a table function: checked by `_check_function` when the walk reaches it
    name = table.name.lower()
    if schema == AI_SCHEMA:
        if name not in ai_views:
            raise GuardError(
                f"ai.{table.name} does not exist. The ai views are: {', '.join(sorted(ai_views))}."
            )
        return
    if name in _visible_cte_names(table) or name in ai_views:
        return
    raise GuardError(
        f"Table '{table.name}' is not an ai view or a CTE in scope. "
        f"The ai views are: {', '.join(sorted(ai_views))}."
    )


def _visible_cte_names(node: exp.Expr) -> set[str]:
    """CTE names visible from `node`, following Postgres scoping: a CTE sees the
    CTEs before it in its WITH (and itself only under RECURSIVE); the query
    body sees all of them; nothing outside the query that owns the WITH does."""
    visible: set[str] = set()
    child: exp.Expr = node
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.With) and isinstance(child, exp.CTE):
            ctes = list(parent.expressions)
            index = next(i for i, cte in enumerate(ctes) if cte is child)
            upto = index + 1 if parent.args.get("recursive") else index
            visible.update(cte.alias_or_name.lower() for cte in ctes[:upto])
        else:
            with_ = parent.args.get("with") or parent.args.get("with_")
            if isinstance(with_, exp.With) and child is not with_:
                visible.update(cte.alias_or_name.lower() for cte in with_.expressions)
        child, parent = parent, parent.parent
    return visible


def _function_name(func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous | exp.AnonymousAggFunc):
        return str(func.name).lower()
    return func.sql_name().lower()


def _check_function(func: exp.Func) -> None:
    name = _function_name(func)
    qualifier = _function_qualifier(func)
    if qualifier is not None:
        if qualifier == AI_SCHEMA and name in AI_FUNCTIONS:
            return
        raise GuardError(
            f"Function {qualifier}.{name}() is not allowed. The only schema-qualified functions "
            f"allowed are {', '.join(sorted(f'ai.{f}' for f in AI_FUNCTIONS))}."
        )
    if name in ALLOWED_FUNCTIONS or name in AI_FUNCTIONS:
        return
    raise GuardError(
        f"Function {name}() is not on the allow-list. Use aggregates, window functions, math, "
        "date/time, string, coalesce/nullif/greatest/least, casts, ai.returns_between, or ai.today_ny."
    )


def _function_qualifier(func: exp.Func) -> str | None:
    parent = func.parent
    if isinstance(parent, exp.Dot) and parent.expression is func:
        return str(parent.this.sql(dialect="postgres")).strip('"').lower()
    if isinstance(parent, exp.Table) and parent.this is func:
        return str(parent.db).lower() if parent.db else None
    return None


def _check_cast_type(data_type: exp.DataType) -> None:
    if data_type.this not in _ALLOWED_CAST_TYPES:
        raise GuardError(
            f"Cast to {data_type.sql(dialect='postgres')} is not allowed. Cast to a number, text, "
            "date, time, timestamp, interval, boolean, or json type."
        )


def _first_line(error: BaseException) -> str:
    text = str(error).strip() or type(error).__name__
    return text.splitlines()[0][:300]
