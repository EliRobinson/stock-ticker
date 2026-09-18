"""The EDGAR fixture loader shared by `tests/unit/test_edgar.py` and
`tests/integration/test_edgar_sync.py`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data
