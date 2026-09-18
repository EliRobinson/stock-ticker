import pytest
from pydantic import ValidationError

from stockticker.models.notes import NotePut


def test_note_put_trims_body() -> None:
    note = NotePut(start_date="2024-01-01", body="  hello  ")
    assert note.body == "hello"


def test_note_put_rejects_blank_body() -> None:
    with pytest.raises(ValidationError):
        NotePut(start_date="2024-01-01", body="   ")


def test_note_put_rejects_body_over_max_length() -> None:
    with pytest.raises(ValidationError):
        NotePut(start_date="2024-01-01", body="x" * 10_001)


def test_note_put_defaults_cik_and_end_date_to_none() -> None:
    note = NotePut(start_date="2024-01-01", body="ok")
    assert note.cik is None
    assert note.end_date is None
