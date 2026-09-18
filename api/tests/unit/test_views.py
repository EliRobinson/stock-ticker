from pydantic import TypeAdapter

from stockticker.models.views import ChartSpec, TableSpec, ViewSpec


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
