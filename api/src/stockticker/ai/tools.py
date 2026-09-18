"""The three Ask tools (system design §6, "Tools").

Each tool is defined once, as a name plus a Pydantic input model. The JSON
schema sent to Anthropic is generated from that model (`anthropic_tools()`),
and the model's input is validated against the same model before the tool
runs, so the two can never drift apart.

Every tool result the model reads is wrapped in `<untrusted_data>` tags
(`wrap_untrusted`): query results carry Company names, Event titles, Note
bodies, and filing text, none of which are instructions.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from anthropic.types import ToolParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stockticker.ai.executor import Column, SqlExecutor, ToolError
from stockticker.ai.guard import AI_VIEWS, ROW_LIMIT, GuardError, guard_sql
from stockticker.models.views import ChartSeries, TableColumn, TableSpec, TimeseriesChartSpec

MODEL_ROW_LIMIT = 200
MODEL_BYTE_LIMIT = 16 * 1024
MAX_CELL_CHARS = 1_000
MAX_CHART_SERIES = 8
SIGNIFICANT_DIGITS = 6

DATE_TYPES = frozenset({"date", "timestamp", "timestamptz"})
NUMERIC_TYPES = frozenset({"int2", "int4", "int8", "numeric", "float4", "float8"})

ValueFormat = Literal[
    "text", "integer", "number", "currency", "compact_currency", "percent", "fraction_as_percent", "date",
    "datetime",
]  # fmt: skip
NumberFormat = Literal["integer", "number", "currency", "compact_currency", "percent", "fraction_as_percent"]

_FORMAT_HELP = (
    "How the web app formats the value. `percent`: the value is already in percent (12.5 -> 12.5%). "
    "`fraction_as_percent`: the value is a fraction (0.125 -> 12.5%). `compact_currency`: $2.9T."
)


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSqlInput(_ToolInput):
    sql: str = Field(description="One Postgres SELECT (or WITH ... SELECT) over the ai views and functions.")
    purpose: str = Field(description="One short sentence: what this query is for. Shown to the user.")


class ShowTableColumn(_ToolInput):
    key: str = Field(description="A column name from the result.")
    label: str = Field(description="Column header shown to the user.")
    format: ValueFormat | None = Field(default=None, description=_FORMAT_HELP)


class ShowTableInput(_ToolInput):
    result_id: str = Field(description="A result_id returned by an earlier run_sql call in this answer.")
    title: str = Field(description="Table title shown to the user.")
    columns: Annotated[list[ShowTableColumn], Field(min_length=1)] = Field(
        description="Columns to show, in order."
    )


class ShowChartSeries(_ToolInput):
    key: str = Field(description="A numeric column name from the result.")
    label: str = Field(description="Legend label for this series.")


class ShowChartInput(_ToolInput):
    result_id: str = Field(description="A result_id returned by an earlier run_sql call in this answer.")
    title: str = Field(description="Chart title shown to the user.")
    x: str = Field(description="The date (or timestamp) column for the x axis.")
    series: Annotated[list[ShowChartSeries], Field(min_length=1, max_length=MAX_CHART_SERIES)] = Field(
        description=f"One to {MAX_CHART_SERIES} numeric columns to plot."
    )
    y_format: NumberFormat | None = Field(default=None, description=_FORMAT_HELP)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[_ToolInput]


RUN_SQL = ToolDefinition(
    name="run_sql",
    description=(
        "Run one read-only SELECT against the ai views and functions. Returns result_id, columns, "
        "up to 200 rows (numbers rounded to 6 significant digits), row_count, and truncated. "
        "Errors come back as text you can use to fix the query."
    ),
    input_model=RunSqlInput,
)
SHOW_TABLE = ToolDefinition(
    name="show_table",
    description=(
        "Display an earlier run_sql result to the user as a table. Use a result_id you have already "
        "seen; call it on a later turn than the run_sql that produced it."
    ),
    input_model=ShowTableInput,
)
SHOW_CHART = ToolDefinition(
    name="show_chart",
    description=(
        "Display an earlier run_sql result to the user as a time-series line chart. x must be a date "
        f"column; at most {MAX_CHART_SERIES} numeric series. Use a result_id you have already seen."
    ),
    input_model=ShowChartInput,
)
TOOLS: tuple[ToolDefinition, ...] = (RUN_SQL, SHOW_TABLE, SHOW_CHART)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def anthropic_tools() -> list[ToolParam]:
    return [
        ToolParam(
            name=tool.name,
            description=tool.description,
            input_schema=_inline_refs(tool.input_model.model_json_schema()),
        )
        for tool in TOOLS
    ]


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic puts nested models under `$defs` and points at them with
    `$ref`. Inline them, and drop the `title`s, which only cost tokens."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {
                key: (
                    {name: resolve(sub) for name, sub in value.items()}
                    if key == "properties"
                    else resolve(value)
                )
                for key, value in node.items()
                if key not in {"$defs", "title"}
            }
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved = resolve(schema)
    assert isinstance(resolved, dict)
    return resolved


# --- results -------------------------------------------------------------


@dataclass
class CachedResult:
    result_id: str
    columns: list[Column]
    rows: list[tuple[Any, ...]]
    row_count: int
    step: int


@dataclass
class ToolOutcome:
    """What one tool call produced. `output` goes to the browser in
    `tool-output-available`; `model_content` goes to the model."""

    output: dict[str, Any] | None = None
    model_content: str = ""
    error: str | None = None
    view: dict[str, Any] | None = None
    view_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class AnswerTools:
    """Tool state for one answer: the result cache and the current step."""

    executor: SqlExecutor
    ai_views: frozenset[str] = AI_VIEWS
    step: int = 0
    results: dict[str, CachedResult] = field(default_factory=dict)
    views_shown: int = 0

    async def run(self, name: str, raw_input: Any) -> ToolOutcome:
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            return _error(f"Unknown tool {name!r}. The tools are: {', '.join(TOOLS_BY_NAME)}.")
        try:
            parsed = tool.input_model.model_validate(raw_input)
        except ValidationError as error:
            return _error(f"Invalid input for {name}: {_validation_summary(error)}")
        handlers: dict[str, Callable[[Any], Awaitable[ToolOutcome]]] = {
            RUN_SQL.name: self._run_sql,
            SHOW_TABLE.name: self._show_table,
            SHOW_CHART.name: self._show_chart,
        }
        try:
            return await handlers[name](parsed)
        except (GuardError, ToolError) as error:
            return _error(str(error))

    async def _run_sql(self, request: RunSqlInput) -> ToolOutcome:
        guarded = guard_sql(request.sql, ai_views=self.ai_views)
        result = await self.executor.execute(guarded.wrapped_sql)
        result_id = f"r{len(self.results) + 1}"
        cached = CachedResult(
            result_id=result_id,
            columns=result.columns,
            rows=result.rows[:ROW_LIMIT],
            row_count=min(len(result.rows), ROW_LIMIT),
            step=self.step,
        )
        self.results[result_id] = cached
        payload = model_payload(cached, more_than_limit=len(result.rows) > ROW_LIMIT)
        return ToolOutcome(output=payload, model_content=wrap_untrusted(payload))

    def _seen_result(self, result_id: str) -> CachedResult:
        cached = self.results.get(result_id)
        if cached is None:
            raise ToolError(
                f"Unknown result_id {result_id!r}. Use a result_id from a run_sql call earlier in this "
                "answer (results from earlier answers are gone; run the query again)."
            )
        if cached.step >= self.step:
            raise ToolError(
                f"{result_id} was produced in this same turn, so you have not seen it yet. "
                "Read the result first, then show it on your next turn."
            )
        return cached

    async def _show_table(self, request: ShowTableInput) -> ToolOutcome:
        cached = self._seen_result(request.result_id)
        names = _unique_column_names(cached)
        _require_columns(cached, [column.key for column in request.columns], names)
        view_id = self._next_view_id()
        spec = TableSpec(
            id=view_id,
            title=request.title,
            columns=[TableColumn(key=c.key, label=c.label, format=c.format) for c in request.columns],
            rows=_row_dicts(cached, [c.key for c in request.columns]),
        )
        return self._view_outcome(view_id, spec.model_dump(mode="json"), len(spec.rows))

    async def _show_chart(self, request: ShowChartInput) -> ToolOutcome:
        cached = self._seen_result(request.result_id)
        names = _unique_column_names(cached)
        keys = [request.x, *(series.key for series in request.series)]
        _require_columns(cached, keys, names)
        types = {column.name: column.type for column in cached.columns}
        if types[request.x] not in DATE_TYPES:
            raise ToolError(f"x must be a date column; {request.x!r} is {types[request.x]}.")
        for series in request.series:
            if series.key == request.x:
                raise ToolError(f"{series.key!r} is the x column; it cannot also be a series.")
            if types[series.key] not in NUMERIC_TYPES:
                raise ToolError(f"Series {series.key!r} must be numeric; it is {types[series.key]}.")
        view_id = self._next_view_id()
        spec = TimeseriesChartSpec(
            id=view_id,
            title=request.title,
            x=request.x,
            series=[ChartSeries(key=s.key, label=s.label) for s in request.series],
            y_format=request.y_format,
            rows=_row_dicts(cached, keys),
        )
        return self._view_outcome(view_id, spec.model_dump(mode="json"), len(spec.rows))

    def _next_view_id(self) -> str:
        """Unique within the answer (one assistant message), which is the
        scope the AI SDK client keys `data-view` parts by."""
        self.views_shown += 1
        return f"view-{self.views_shown}"

    @staticmethod
    def _view_outcome(view_id: str, spec: dict[str, Any], row_count: int) -> ToolOutcome:
        output = {"view_id": view_id, "kind": spec["kind"], "rows_shown": row_count}
        return ToolOutcome(output=output, model_content=wrap_untrusted(output), view=spec, view_id=view_id)


def _error(message: str) -> ToolOutcome:
    return ToolOutcome(error=message, model_content=wrap_untrusted({"error": message}))


def _validation_summary(error: ValidationError) -> str:
    problems = []
    for item in error.errors()[:5]:
        location = ".".join(str(part) for part in item["loc"]) or "input"
        problems.append(f"{location}: {item['msg']}")
    return "; ".join(problems)


def _unique_column_names(cached: CachedResult) -> list[str]:
    names = [column.name for column in cached.columns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ToolError(
            f"{cached.result_id} has duplicate column names ({', '.join(duplicates)}). "
            "Alias them in run_sql, then show the new result."
        )
    return names


def _require_columns(cached: CachedResult, keys: list[str], names: list[str]) -> None:
    missing = [key for key in keys if key not in names]
    if missing:
        raise ToolError(
            f"{cached.result_id} has no column {', '.join(repr(k) for k in missing)}. "
            f"Its columns are: {', '.join(names)}."
        )


def _row_dicts(cached: CachedResult, keys: list[str]) -> list[dict[str, Any]]:
    indexes = {column.name: i for i, column in enumerate(cached.columns)}
    return [{key: json_value(row[indexes[key]]) for key in keys} for row in cached.rows]


# --- serialization ---------------------------------------------------------


def json_value(value: Any, *, significant_digits: int | None = None) -> Any:
    """A JSON-safe copy of a value asyncpg returned. With `significant_digits`,
    non-integer numbers are rounded (integers such as ids and volumes stay exact)."""
    if value is None or isinstance(value, bool | str | int):
        return value
    if isinstance(value, Decimal | float):
        number = float(value)
        if not math.isfinite(number):
            return None
        if significant_digits is not None:
            number = float(f"{number:.{significant_digits}g}")
        if number.is_integer() and abs(number) < 2**53:
            return int(number)
        return number
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [json_value(item, significant_digits=significant_digits) for item in value]
    if isinstance(value, dict):
        return {str(k): json_value(v, significant_digits=significant_digits) for k, v in value.items()}
    return str(value)


def _clip(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + " [cut]", True
    return value, False


def model_payload(cached: CachedResult, *, more_than_limit: bool) -> dict[str, Any]:
    """The run_sql result the model reads: at most 200 rows and 16 KB."""
    clipped_any = False
    rows: list[list[Any]] = []
    for row in cached.rows[:MODEL_ROW_LIMIT]:
        cells = []
        for value in row:
            cell, clipped = _clip(json_value(value, significant_digits=SIGNIFICANT_DIGITS))
            clipped_any = clipped_any or clipped
            cells.append(cell)
        rows.append(cells)

    def payload(count: int) -> dict[str, Any]:
        return {
            "result_id": cached.result_id,
            "columns": [{"name": column.name, "type": column.type} for column in cached.columns],
            "rows": rows[:count],
            "row_count": cached.row_count,
            "row_count_is_capped": more_than_limit,
            "truncated": more_than_limit or clipped_any or count < cached.row_count,
        }

    count = len(rows)
    while count > 0 and _json_size(payload(count)) > MODEL_BYTE_LIMIT:
        count = max(0, min(count - 1, count * MODEL_BYTE_LIMIT // _json_size(payload(count))))
    return payload(count)


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def wrap_untrusted(value: Any) -> str:
    """JSON inside `<untrusted_data>` tags. `<` is escaped (valid JSON, same
    value), so data can never close the tag early."""
    body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    return f"<untrusted_data>{body}</untrusted_data>"
