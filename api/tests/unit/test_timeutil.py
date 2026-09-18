from datetime import date

from stockticker.timeutil import NY_TZ, now_ny, today_ny


def test_today_ny_returns_a_date() -> None:
    assert isinstance(today_ny(), date)


def test_now_ny_is_timezone_aware_in_new_york() -> None:
    now = now_ny()
    assert now.tzinfo is not None
    assert now.tzinfo == NY_TZ
