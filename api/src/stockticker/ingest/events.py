"""The `details` contract of split Events, shared by the writer
(`corporate_actions_sync`) and the reader (`market_caps_rebuild`).

A `split` or `reverse_split` Event stores the provider's rates as strings:
`{"old_rate": "1", "new_rate": "4"}` for a 4-for-1, and
`{"old_rate": "10", "new_rate": "1"}` for a 1-for-10 reverse split.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class SplitRatioError(ValueError):
    pass


def split_details(old_rate: Decimal | int | str, new_rate: Decimal | int | str) -> dict[str, str]:
    return {"old_rate": str(old_rate), "new_rate": str(new_rate)}


def split_ratio(details: dict[str, Any]) -> Decimal:
    """New shares per old share: 4 for a 4-for-1, 0.1 for a 1-for-10."""
    try:
        ratio = Decimal(str(details["new_rate"])) / Decimal(str(details["old_rate"]))
    except (KeyError, InvalidOperation, ZeroDivisionError) as exc:
        raise SplitRatioError(f"no usable split ratio in {details!r}") from exc
    if not ratio.is_finite() or ratio <= 0:
        raise SplitRatioError(f"split ratio must be positive, got {ratio}")
    return ratio
