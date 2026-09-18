"""Guards that the Pydantic copies of two DB `CHECK` constraints
(`EventKind`, Notes' body length) never silently drift from the schema
(system design §5 review, DRY pass): the model and the constraint are two
places stating the same rule on purpose (the model gives a fast, friendly
422 before a row ever reaches Postgres; the constraint is the real
backstop) -- this test is what keeps that duplication honest."""

from __future__ import annotations

import re
from typing import get_args

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from stockticker.models.events import EventKind
from stockticker.models.notes import MAX_BODY_LEN, MIN_BODY_LEN

_QUOTED_LITERAL = re.compile(r"'([^']*)'::text")


async def test_events_kind_check_matches_event_kind_literal(app_writer_engine: AsyncEngine) -> None:
    async with app_writer_engine.connect() as conn:
        definition = await conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'events'::regclass AND contype = 'c' AND conname = 'events_kind_check'"
            )
        )
    assert definition is not None, "events_kind_check is gone -- update this test with the new name"
    db_kinds = set(_QUOTED_LITERAL.findall(definition))
    assert db_kinds == set(get_args(EventKind)), (
        "EventKind and the events.kind CHECK constraint have drifted apart -- "
        f"DB has {db_kinds}, EventKind has {set(get_args(EventKind))}"
    )


async def test_notes_body_check_matches_model_length_limits(app_writer_engine: AsyncEngine) -> None:
    async with app_writer_engine.connect() as conn:
        definition = await conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'notes'::regclass AND contype = 'c' AND conname = 'notes_body_check'"
            )
        )
    assert definition is not None, "notes_body_check is gone -- update this test with the new name"
    db_numbers = {int(n) for n in re.findall(r"\d+", definition)}
    assert MIN_BODY_LEN in db_numbers, f"MIN_BODY_LEN={MIN_BODY_LEN} not in the constraint: {definition}"
    assert MAX_BODY_LEN in db_numbers, f"MAX_BODY_LEN={MAX_BODY_LEN} not in the constraint: {definition}"
