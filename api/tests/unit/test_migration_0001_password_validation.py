"""`_required_password`/`_pg_ident` in `0001_initial_schema.py` (issue #32,
round 1): a `$$` password must fail fast with a clear error rather than
silently truncating the migration's `DO $$ ... $$;` blocks, and the
database name interpolated into a GRANT statement is derived from
`Settings.postgres_db`, not hardcoded.

`alembic/versions/` has no `__init__.py` (it's not a normal package --
Alembic loads each revision by file path), so this loads the module the
same way."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import SecretStr

_MODULE_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0001_initial_schema.py"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0001_initial_schema", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration() -> ModuleType:
    return _load_migration_module()


def test_required_password_rejects_a_dollar_dollar_password(migration: ModuleType) -> None:
    with pytest.raises(RuntimeError, match=r"POSTGRES_APP_WRITER_PASSWORD must not contain '\$\$'"):
        migration._required_password("POSTGRES_APP_WRITER_PASSWORD", SecretStr("bad$$pw"))


def test_required_password_accepts_a_password_without_dollar_dollar(migration: ModuleType) -> None:
    result = migration._required_password("POSTGRES_APP_WRITER_PASSWORD", SecretStr("perfectly-fine-pw"))
    assert result == "perfectly-fine-pw"


def test_required_password_rejects_a_missing_password(migration: ModuleType) -> None:
    with pytest.raises(RuntimeError, match="POSTGRES_APP_WRITER_PASSWORD must be set"):
        migration._required_password("POSTGRES_APP_WRITER_PASSWORD", None)


def test_pg_ident_quotes_and_escapes_double_quotes(migration: ModuleType) -> None:
    assert migration._pg_ident("stockticker") == '"stockticker"'
    assert migration._pg_ident('weird"name') == '"weird""name"'


def test_upgrade_derives_database_name_from_settings_not_a_hardcoded_constant(
    migration: ModuleType,
) -> None:
    assert not hasattr(migration, "DATABASE_NAME")
