"""The one place "today" gets computed. Containers run in UTC; the domain
(Trading Days, the scheduler, the market clock) runs in New York time.
Use `today_ny()` instead of `datetime.date.today()` anywhere that means
"today" in the market's sense."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")


def now_ny() -> datetime:
    return datetime.now(NY_TZ)


def today_ny() -> date:
    return now_ny().date()
