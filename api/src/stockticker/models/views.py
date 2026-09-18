"""`data-view` payloads streamed by `/api/v1/chat` (system design §6).

`show_table`/`show_chart` build these from a `run_sql` result the model has
already seen, so the text answer and the rendered view can never disagree.

Both are discriminated on `kind`, not `type` (`type` collides with the
`data-view` envelope's own `type` field in the AI SDK stream). `ChartSpec`
today has exactly one member, `TimeseriesChartSpec` (`kind="timeseries"`);
when a second chart kind is added, change `ChartSpec`'s alias to
`Annotated[TimeseriesChartSpec | NewChartSpec, Field(discriminator="kind")]`
-- callers that only ever imported `ChartSpec` don't need to change."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class TableColumn(BaseModel):
    key: str
    label: str
    format: str | None = None


class TableSpec(BaseModel):
    kind: Literal["table"] = "table"
    id: str
    title: str
    columns: list[TableColumn]
    rows: list[dict[str, Any]]


class ChartSeries(BaseModel):
    key: str
    label: str


class TimeseriesChartSpec(BaseModel):
    kind: Literal["timeseries"] = "timeseries"
    id: str
    title: str
    x: str
    series: list[ChartSeries]
    y_format: str | None = None
    rows: list[dict[str, Any]]


ChartSpec = TimeseriesChartSpec
ViewSpec = Annotated[TableSpec | ChartSpec, Field(discriminator="kind")]
