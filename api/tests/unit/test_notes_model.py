from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from stockticker.models.notes import NotePut
from stockticker.timeutil import today_ny

_A_DATE = date(2024, 1, 1)

# `end_date` is an honest `date` (not `date | None`) on NotePut -- filled in
# from `start_date` by a `mode="before"` validator when the request body
# omits it. That only runs on `model_validate` (how FastAPI actually
# constructs the body), not on direct keyword construction, so tests that
# want the default use a plain dict here rather than `NotePut(...)`.


def test_note_put_trims_body() -> None:
    note = NotePut.model_validate({"start_date": _A_DATE, "body": "  hello  "})
    assert note.body == "hello"


def test_note_put_rejects_blank_body() -> None:
    with pytest.raises(ValidationError):
        NotePut.model_validate({"start_date": _A_DATE, "body": "   "})


def test_note_put_rejects_body_over_max_length() -> None:
    with pytest.raises(ValidationError):
        NotePut.model_validate({"start_date": _A_DATE, "body": "x" * 10_001})


def test_note_put_rejects_nul_byte_in_body() -> None:
    with pytest.raises(ValidationError):
        NotePut.model_validate({"start_date": _A_DATE, "body": "hello\x00world"})


def test_note_put_defaults_cik_to_none() -> None:
    note = NotePut.model_validate({"start_date": _A_DATE, "body": "ok"})
    assert note.cik is None


def test_note_put_defaults_end_date_to_start_date() -> None:
    # system design §5, amended: "end_date defaults to start_date" -- a
    # real (non-null) date, not the un-implemented stub behavior the
    # foundation's own test once asserted.
    note = NotePut.model_validate({"start_date": _A_DATE, "body": "ok"})
    assert note.end_date == _A_DATE


def test_note_put_rejects_end_date_before_start_date() -> None:
    with pytest.raises(ValidationError):
        NotePut(start_date=date(2024, 1, 2), end_date=date(2024, 1, 1), body="ok")


def test_note_put_rejects_date_before_1990() -> None:
    with pytest.raises(ValidationError):
        NotePut.model_validate({"start_date": date(1989, 12, 31), "body": "ok"})


def test_note_put_rejects_date_past_horizon() -> None:
    too_far = today_ny() + timedelta(days=366)
    with pytest.raises(ValidationError):
        NotePut.model_validate({"start_date": too_far, "body": "ok"})


def test_note_put_accepts_date_at_horizon() -> None:
    at_horizon = today_ny() + timedelta(days=365)
    note = NotePut(start_date=at_horizon, end_date=at_horizon, body="ok")
    assert note.start_date == at_horizon
