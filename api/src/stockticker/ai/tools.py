"""The three Ask tools (system design §6, "Tools").

Each tool is defined once, as a `ToolDefinition`: a name, a Pydantic input
model, and its handler. The JSON schema sent to Anthropic is generated from
the input model (`anthropic_tools()`), and the model's input is validated
against the same model before the handler runs, so the two can never drift.

A tool never ends the answer. Every failure, expected or not, comes back to
the model as a `ToolFailure` it can read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from anthropic.types import ToolParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stockticker.ai.executor import Column, SqlExecutor, ToolError
from stockticker.ai.guard import DEFAULT_SURFACE, ROW_LIMIT, AiSurface, GuardError, guard_sql
from stockticker.ai.serialize import (
    MODEL_ROW_LIMIT,
    SIGNIFICANT_DIGITS,
    display_value,
    inline_schema_refs,
    model_payload,
    wrap_untrusted,
)
from stockticker.logging import get_logger
from stockticker.models.views import (
    ChartSeries,
    TableColumn,
    TableSpec,
    TimeseriesChartSpec,
    ViewSpec,
)

logger = get_logger(__name__)

MAX_CHART_SERIES = 8

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
INTERNAL_TOOL_ERROR = "The tool failed with an internal error. Try a different query."


# --- inputs ------------------------------------------------------------------


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


# --- outcomes ------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSuccess:
    """`output` goes to the browser in `tool-output-available` and, wrapped as
    untrusted data, to the model. `view`, if any, becomes a `data-view` part."""

    output: dict[str, Any]
    view: ViewSpec | None = None

    @property
    def model_content(self) -> str:
        return wrap_untrusted(self.output)


@dataclass(frozen=True)
class ToolFailure:
    """`message` goes to the browser in `tool-output-error` and, wrapped as
    untrusted data, to the model, which can often fix its call."""

    message: str

    @property
    def model_content(self) -> str:
        return wrap_untrusted({"error": self.message})


ToolOutcome = ToolSuccess | ToolFailure


# --- per-answer state ------------------------------------------------------------


@dataclass
class CachedResult:
    result_id: str
    columns: list[Column]
    rows: list[tuple[Any, ...]]
    row_count: int
    step: int


@dataclass
class AnswerTools:
    """Tool state for one answer: the result cache and the current step."""

    executor: SqlExecutor
    surface: AiSurface = DEFAULT_SURFACE
    step: int = 0
    results: dict[str, CachedResult] = field(default_factory=dict)
    views_shown: int = 0

    async def run(self, name: str, raw_input: Any) -> ToolOutcome:
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            return ToolFailure(f"Unknown tool {name!r}. The tools are: {', '.join(TOOLS_BY_NAME)}.")
        try:
            parsed = tool.input_model.model_validate(raw_input)
        except ValidationError as error:
            return ToolFailure(f"Invalid input for {name}: {_validation_summary(error)}")
        try:
            return await tool.handler(self, parsed)
        except (GuardError, ToolError) as error:
            return ToolFailure(str(error))
        except Exception:
            logger.exception("ai_tool_failed", tool=name)
            return ToolFailure(INTERNAL_TOOL_ERROR)

    def seen_result(self, result_id: str) -> CachedResult:
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

    def next_view_id(self) -> str:
        """Unique within the answer (one assistant message), which is the
        scope the AI SDK client keys `data-view` parts by."""
        self.views_shown += 1
        return f"view-{self.views_shown}"


# --- handlers --------------------------------------------------------------------


async def _run_sql(state: AnswerTools, request: RunSqlInput) -> ToolOutcome:
    guarded = guard_sql(request.sql, surface=state.surface)
    result = await state.executor.execute(guarded.wrapped_sql)
    result_id = f"r{len(state.results) + 1}"
    cached = CachedResult(
        result_id=result_id,
        columns=result.columns,
        rows=result.rows[:ROW_LIMIT],
        row_count=min(len(result.rows), ROW_LIMIT),
        step=state.step,
    )
    state.results[result_id] = cached
    return ToolSuccess(
        output=model_payload(
            result_id=result_id,
            columns=[(column.name, column.type) for column in cached.columns],
            rows=cached.rows,
            row_count=cached.row_count,
            row_count_is_capped=len(result.rows) > ROW_LIMIT,
        )
    )


async def _show_table(state: AnswerTools, request: ShowTableInput) -> ToolOutcome:
    cached = state.seen_result(request.result_id)
    keys = [column.key for column in request.columns]
    _require_columns(cached, keys)
    spec = TableSpec(
        id=state.next_view_id(),
        title=request.title,
        columns=[TableColumn(key=c.key, label=c.label, format=c.format) for c in request.columns],
        rows=_row_dicts(cached, keys),
    )
    return _view_success(spec)


async def _show_chart(state: AnswerTools, request: ShowChartInput) -> ToolOutcome:
    cached = state.seen_result(request.result_id)
    keys = [request.x, *(series.key for series in request.series)]
    _require_columns(cached, keys)
    types = {column.name: column.type for column in cached.columns}
    if types[request.x] not in DATE_TYPES:
        raise ToolError(f"x must be a date column; {request.x!r} is {types[request.x]}.")
    for series in request.series:
        if series.key == request.x:
            raise ToolError(f"{series.key!r} is the x column; it cannot also be a series.")
        if types[series.key] not in NUMERIC_TYPES:
            raise ToolError(f"Series {series.key!r} must be numeric; it is {types[series.key]}.")
    spec = TimeseriesChartSpec(
        id=state.next_view_id(),
        title=request.title,
        x=request.x,
        series=[ChartSeries(key=s.key, label=s.label) for s in request.series],
        y_format=request.y_format,
        rows=_row_dicts(cached, keys),
    )
    return _view_success(spec)


def _view_success(spec: TableSpec | TimeseriesChartSpec) -> ToolSuccess:
    return ToolSuccess(
        output={"view_id": spec.id, "kind": spec.kind, "rows_shown": len(spec.rows)}, view=spec
    )


def _validation_summary(error: ValidationError) -> str:
    problems = []
    for item in error.errors()[:5]:
        location = ".".join(str(part) for part in item["loc"]) or "input"
        problems.append(f"{location}: {item['msg']}")
    return "; ".join(problems)


def _require_columns(cached: CachedResult, keys: list[str]) -> None:
    names = [column.name for column in cached.columns]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ToolError(
            f"{cached.result_id} has duplicate column names ({', '.join(duplicates)}). "
            "Alias them in run_sql, then show the new result."
        )
    missing = [key for key in keys if key not in names]
    if missing:
        raise ToolError(
            f"{cached.result_id} has no column {', '.join(repr(k) for k in missing)}. "
            f"Its columns are: {', '.join(names)}."
        )


def _row_dicts(cached: CachedResult, keys: list[str]) -> list[dict[str, Any]]:
    indexes = {column.name: i for i, column in enumerate(cached.columns)}
    return [{key: display_value(row[indexes[key]]) for key in keys} for row in cached.rows]


# --- definitions --------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[_ToolInput]
    handler: Callable[[AnswerTools, Any], Awaitable[ToolOutcome]]


RUN_SQL = ToolDefinition(
    name="run_sql",
    description=(
        "Run one read-only SELECT against the ai views and functions. Returns result_id, columns, "
        f"up to {MODEL_ROW_LIMIT} rows (numbers rounded to {SIGNIFICANT_DIGITS} significant digits), "
        "row_count, and truncated. "
        "Errors come back as text you can use to fix the query."
    ),
    input_model=RunSqlInput,
    handler=_run_sql,
)
SHOW_TABLE = ToolDefinition(
    name="show_table",
    description=(
        "Display an earlier run_sql result to the user as a table. Use a result_id you have already "
        "seen; call it on a later turn than the run_sql that produced it."
    ),
    input_model=ShowTableInput,
    handler=_show_table,
)
SHOW_CHART = ToolDefinition(
    name="show_chart",
    description=(
        "Display an earlier run_sql result to the user as a time-series line chart. x must be a date "
        f"column; at most {MAX_CHART_SERIES} numeric series. Use a result_id you have already seen."
    ),
    input_model=ShowChartInput,
    handler=_show_chart,
)
TOOLS: tuple[ToolDefinition, ...] = (RUN_SQL, SHOW_TABLE, SHOW_CHART)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
TOOL_NAMES = frozenset(TOOLS_BY_NAME)


def anthropic_tools() -> list[ToolParam]:
    return [
        ToolParam(
            name=tool.name,
            description=tool.description,
            input_schema=inline_schema_refs(tool.input_model.model_json_schema()),
        )
        for tool in TOOLS
    ]
