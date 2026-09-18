import pytest
from pydantic import TypeAdapter, ValidationError

from stockticker.models.views import ChartSpec, TableColumn, TableSpec, ViewSpec


def test_table_spec_kind_defaults_to_table() -> None:
    spec = TableSpec(id="t1", title="Top movers", columns=[], rows=[])
    assert spec.kind == "table"


def test_chart_spec_kind_defaults_to_timeseries() -> None:
    spec = ChartSpec(id="c1", title="Close over time", x="trade_date", series=[], rows=[])
    assert spec.kind == "timeseries"


def test_view_spec_discriminates_by_kind() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(ViewSpec)
    table = adapter.validate_python({"kind": "table", "id": "t1", "title": "T", "columns": [], "rows": []})
    chart = adapter.validate_python(
        {"kind": "timeseries", "id": "c1", "title": "C", "x": "trade_date", "series": [], "rows": []}
    )
    assert isinstance(table, TableSpec)
    assert isinstance(chart, ChartSpec)


def test_the_schema_lists_the_value_formats_the_web_app_can_draw() -> None:
    table_format = TableSpec.model_json_schema()["$defs"]["TableColumn"]["properties"]["format"]
    assert "compact_currency" in table_format["anyOf"][0]["enum"]
    y_format = ChartSpec.model_json_schema()["properties"]["y_format"]
    assert "date" not in y_format["anyOf"][0]["enum"]
    with pytest.raises(ValidationError):
        TableColumn.model_validate({"key": "k", "label": "K", "format": "bogus"})
