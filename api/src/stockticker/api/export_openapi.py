"""Writes the API's OpenAPI schema to `api/openapi.json` (system design §5's
read/write endpoints and everything else `app.py` registers).

`web`'s `pnpm gen:api` reads this file to generate TypeScript types (system
design §2: "Types are generated from the API's OpenAPI schema, and the
generated file is committed"), so it is committed here too and regenerated
by this script whenever a route or model changes:

    uv run python -m stockticker.api.export_openapi
"""

from __future__ import annotations

import json
from pathlib import Path

from stockticker.api.app import app

OUTPUT_PATH = Path(__file__).resolve().parents[3] / "openapi.json"


def export_openapi(output_path: Path = OUTPUT_PATH) -> Path:
    schema = app.openapi()
    output_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    return output_path


def main() -> None:
    path = export_openapi()
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
