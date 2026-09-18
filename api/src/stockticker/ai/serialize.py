"""Turning query results into what the model and the browser read.

Every tool result the model reads is wrapped in `<untrusted_data>` tags
(`wrap_untrusted`): query results carry Company names, Event titles, Note
bodies, and filing text, none of which are instructions.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

MODEL_ROW_LIMIT = 200
MODEL_BYTE_LIMIT = 16 * 1024
MAX_CELL_CHARS = 1_000
SIGNIFICANT_DIGITS = 6
CLIP_MARKER = " [cut]"


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


def clip(value: Any) -> tuple[Any, bool]:
    """Cuts a string longer than `MAX_CELL_CHARS`; says whether it did."""
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + CLIP_MARKER, True
    return value, False


def display_value(value: Any) -> Any:
    """A cell for a table or chart: JSON-safe, full precision, long text cut."""
    cell, _ = clip(json_value(value))
    return cell


def model_payload(
    *,
    result_id: str,
    columns: Sequence[tuple[str, str]],
    rows: Sequence[Sequence[Any]],
    row_count: int,
    row_count_is_capped: bool,
) -> dict[str, Any]:
    """The run_sql result the model reads: at most `MODEL_ROW_LIMIT` rows and
    `MODEL_BYTE_LIMIT` bytes, numbers rounded to `SIGNIFICANT_DIGITS`, long
    text cut."""
    clipped_any = False
    model_rows: list[list[Any]] = []
    for row in rows[:MODEL_ROW_LIMIT]:
        cells = []
        for value in row:
            cell, clipped = clip(json_value(value, significant_digits=SIGNIFICANT_DIGITS))
            clipped_any = clipped_any or clipped
            cells.append(cell)
        model_rows.append(cells)

    def payload(count: int) -> dict[str, Any]:
        return {
            "result_id": result_id,
            "columns": [{"name": name, "type": type_} for name, type_ in columns],
            "rows": model_rows[:count],
            "row_count": row_count,
            "row_count_is_capped": row_count_is_capped,
            "truncated": row_count_is_capped or clipped_any or count < row_count,
        }

    count = len(model_rows)
    while count > 0 and json_size(payload(count)) > MODEL_BYTE_LIMIT:
        count = max(0, min(count - 1, count * MODEL_BYTE_LIMIT // json_size(payload(count))))
    return payload(count)


def compact_json(value: Any) -> str:
    """JSON the way `JSON.stringify` writes it: no spaces, UTF-8 kept as is."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def json_size(value: Any) -> int:
    return len(compact_json(value).encode())


def wrap_untrusted_text(raw: str) -> str:
    """`raw` inside `<untrusted_data>` tags. Every `<` becomes `\\u003c` (the
    same character in JSON), so data can never close the tag early."""
    return f"<untrusted_data>{raw.replace('<', UNTRUSTED_LT)}</untrusted_data>"


def wrap_untrusted(value: Any) -> str:
    """`value` as JSON inside `<untrusted_data>` tags."""
    return wrap_untrusted_text(compact_json(value))


def wrap_untrusted_cut(raw: str, *, max_bytes: int, marker: str) -> str:
    """Like `wrap_untrusted_text`, but cut so the whole result, tags and
    `marker` included, is at most `max_bytes` of UTF-8."""
    escaped = raw.replace("<", UNTRUSTED_LT)
    budget = max_bytes - len(wrap_untrusted_text(marker).encode())
    cut = escaped.encode()[: max(0, budget)].decode(errors="ignore")
    return wrap_untrusted_text(cut + marker)


UNTRUSTED_LT = "\\u003c"


def tool_result_block(tool_use_id: str, content: str, *, is_error: bool = False) -> dict[str, Any]:
    """An Anthropic `tool_result` block. `content` is already wrapped as
    untrusted data."""
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
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
