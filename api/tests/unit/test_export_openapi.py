"""`api/openapi.json` is committed for `web`'s `pnpm gen:api` (system design
§2) -- this guards against it drifting from what the app actually serves."""

from __future__ import annotations

import json

from stockticker.api.app import app
from stockticker.api.export_openapi import OUTPUT_PATH


def test_committed_openapi_json_matches_the_app() -> None:
    committed = json.loads(OUTPUT_PATH.read_text())
    # Round-trip through json so both sides compare plain dicts/lists (the
    # live schema can carry non-JSON-native values FastAPI itself would
    # serialize the same way, e.g. tuples where the file has lists).
    current = json.loads(json.dumps(app.openapi()))
    assert committed == current, (
        "api/openapi.json is stale -- run `uv run python -m stockticker.api.export_openapi` and commit it."
    )


def test_notes_only_exposes_put_and_delete() -> None:
    schema = json.loads(OUTPUT_PATH.read_text())
    methods = set(schema["paths"]["/api/v1/notes/{note_id}"])
    assert methods == {"put", "delete"}
    assert "post" not in schema["paths"]["/api/v1/notes"]
