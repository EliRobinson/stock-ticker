"""Reads Alembic's head revision without shelling out, for
`/api/v1/health/ready` to compare against the DB's `alembic_version`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = "alembic.ini"


def find_api_root(start: Path) -> Path:
    """Walk upward from `start` until a directory containing `alembic.ini`
    is found, rather than a fixed `parents[N]` -- that count silently goes
    stale the moment this file (or `alembic.ini`) moves a directory deeper
    or shallower."""
    for candidate in (start, *start.parents):
        if (candidate / ALEMBIC_INI).is_file():
            return candidate
    raise FileNotFoundError(f"{ALEMBIC_INI} not found in any parent of {start}")


@lru_cache
def get_head_revision() -> str | None:
    api_root = find_api_root(Path(__file__).resolve())
    cfg = Config(str(api_root / ALEMBIC_INI))
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    head: str | None = script.get_current_head()
    return head
