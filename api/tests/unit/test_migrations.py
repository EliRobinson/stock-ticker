"""`find_api_root` walks up from a starting path looking for `alembic.ini`,
rather than a fixed `parents[N]` that goes stale if this file (or
`alembic.ini`) ever moves (round 1 FIX-LATER, issue #32)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stockticker.api.migrations import find_api_root, get_head_revision


def test_find_api_root_walks_up_to_the_directory_with_alembic_ini(tmp_path: Path) -> None:
    (tmp_path / "alembic.ini").touch()
    nested = tmp_path / "src" / "stockticker" / "api"
    nested.mkdir(parents=True)

    assert find_api_root(nested / "migrations.py") == tmp_path


def test_find_api_root_finds_it_at_the_starting_directory(tmp_path: Path) -> None:
    (tmp_path / "alembic.ini").touch()

    assert find_api_root(tmp_path) == tmp_path


def test_find_api_root_raises_when_no_ancestor_has_alembic_ini(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        find_api_root(nested)


def test_get_head_revision_finds_the_real_alembic_ini() -> None:
    """End-to-end sanity check against the real repo layout, not a temp tree."""
    get_head_revision.cache_clear()
    assert get_head_revision() is not None
