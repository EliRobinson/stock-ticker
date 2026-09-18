"""The schema section of the system prompt, read from the database's own
`COMMENT`s on the `ai` views, their columns, and the `ai` functions
(system design §3). It is queried as `ai_reader`, so it describes exactly
what the model can read. Built once per process and cached: the views only
change with a migration, and a migration means a restart.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.ai.guard import AiSurface

_VIEW_COLUMNS_SQL = """
SELECT c.relname AS view_name,
       obj_description(c.oid, 'pg_class') AS view_comment,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS column_type,
       col_description(c.oid, a.attnum) AS column_comment
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = 'ai' AND c.relkind IN ('v', 'm')
ORDER BY c.relname, a.attnum
"""

_FUNCTIONS_SQL = """
SELECT p.proname AS name,
       pg_catalog.pg_get_function_arguments(p.oid) AS arguments,
       pg_catalog.pg_get_function_result(p.oid) AS result,
       obj_description(p.oid, 'pg_proc') AS comment
FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ai'
ORDER BY p.proname, p.oid
"""


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    comment: str | None


@dataclass(frozen=True)
class ViewInfo:
    name: str
    comment: str | None
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    arguments: str
    result: str
    comment: str | None


@dataclass(frozen=True)
class SchemaCatalog:
    views: list[ViewInfo]
    functions: list[FunctionInfo]

    @property
    def view_names(self) -> frozenset[str]:
        return frozenset(view.name for view in self.views)

    @property
    def function_names(self) -> frozenset[str]:
        return frozenset(function.name for function in self.functions)

    @property
    def surface(self) -> AiSurface:
        return AiSurface(views=self.view_names, functions=self.function_names)

    def render(self) -> str:
        lines = ["Views (schema `ai`):"]
        for view in self.views:
            lines.append("")
            lines.append(f"ai.{view.name}" + (f" -- {view.comment}" if view.comment else ""))
            for column in view.columns:
                comment = f" -- {column.comment}" if column.comment else ""
                lines.append(f"  {column.name} {column.type}{comment}")
        if self.functions:
            lines.append("")
            lines.append("Functions (schema `ai`):")
            for function in self.functions:
                lines.append("")
                lines.append(f"ai.{function.name}({function.arguments}) RETURNS {function.result}")
                if function.comment:
                    lines.append(f"  -- {function.comment}")
        return "\n".join(lines)


async def read_schema_catalog(engine: AsyncEngine) -> SchemaCatalog:
    async with engine.connect() as conn:
        column_rows = (await conn.execute(text(_VIEW_COLUMNS_SQL))).all()
        function_rows = (await conn.execute(text(_FUNCTIONS_SQL))).all()
    views: dict[str, ViewInfo] = {}
    for row in column_rows:
        view = views.setdefault(row.view_name, ViewInfo(name=row.view_name, comment=row.view_comment))
        view.columns.append(
            ColumnInfo(name=row.column_name, type=row.column_type, comment=row.column_comment)
        )
    functions = [
        FunctionInfo(name=row.name, arguments=row.arguments, result=row.result, comment=row.comment)
        for row in function_rows
    ]
    return SchemaCatalog(views=list(views.values()), functions=functions)


class SchemaCache:
    def __init__(self) -> None:
        self._catalog: SchemaCatalog | None = None
        self._lock = asyncio.Lock()

    async def get(self, engine: AsyncEngine) -> SchemaCatalog:
        if self._catalog is not None:
            return self._catalog
        async with self._lock:
            if self._catalog is None:
                self._catalog = await read_schema_catalog(engine)
            return self._catalog

    def clear(self) -> None:
        self._catalog = None


schema_cache = SchemaCache()
