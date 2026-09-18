"""Reads Alembic's head revision without shelling out, for
`/api/v1/health/ready` to compare against the DB's `alembic_version`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_API_ROOT = Path(__file__).resolve().parents[3]


@lru_cache
def get_head_revision() -> str | None:
    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    head: str | None = script.get_current_head()
    return head
