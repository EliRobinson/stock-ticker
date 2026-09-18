"""Alpaca REST client (system design §4, ADR 0001).

Two hosts: the trading API (`/v2/clock`, `/v2/calendar`) and the market-data
API (`/v2/stocks/...`, `/v1/corporate-actions`). Every call, including
`get_snapshots(..., attempts=1)` (`quotes_poll`) and `get_clock`, goes
through `stockticker.ingest.http.request` for the shared rate-budget policy;
those single-attempt callers map to `request(..., attempts=1)` rather than
bypassing it -- system design §4: "No retries, because the next tick is
the retry."

`get_bars` and `get_corporate_actions` exhaust pagination themselves,
through the shared `_paged()` helper (loop on `next_page_token`), so a
caller always gets one fully-paged result for the range it asked for;
page tokens are never persisted (system design §4, `bars_backfill`: "Page
tokens are never saved"). `get_calendar` never paginates -- Alpaca's
`/v2/calendar` returns the whole requested range in one response.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Literal, Protocol

import httpx

from stockticker.config import get_settings
from stockticker.ingest.common import FEED_IEX, FEED_SIP, ny_date
from stockticker.ingest.http import MAX_ATTEMPTS, RateBudgetName, build_http_client, request
from stockticker.ingest.providers import ProviderQuote
from stockticker.models.status import MarketClock
from stockticker.timeutil import NY_TZ

TRADING_API_BASE_URL = "https://api.alpaca.markets"
DATA_API_BASE_URL = "https://data.alpaca.markets"

CLOCK_CACHE_SECONDS = 60.0
BARS_PAGE_LIMIT = 10_000
CORPORATE_ACTIONS_PAGE_LIMIT = 1_000
SNAPSHOTS_PATH = "/v2/stocks/snapshots"


def _parse_timestamp(value: str) -> datetime:
    """Alpaca timestamps are RFC-3339 with a `Z` suffix and sometimes more
    than 6 fractional digits -- more precision than `datetime.fromisoformat`
    accepts on some inputs, so fractional seconds are trimmed to 6."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if "." not in value:
        return datetime.fromisoformat(value)
    head, rest = value.split(".", 1)
    for i, ch in enumerate(rest):
        if ch in "+-":
            frac, tz = rest[:i], rest[i:]
            break
    else:
        frac, tz = rest, ""
    frac = (frac + "000000")[:6]
    return datetime.fromisoformat(f"{head}.{frac}{tz}")


def _combine_ny(trade_date: date, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute, tzinfo=NY_TZ)


def _is_open_between(next_open: datetime, next_close: datetime, now: datetime) -> bool:
    """Alpaca's clock shape: while the market is open, `next_close` (today's
    close) comes before `next_open` (the *following* session's open); while
    closed, `next_open` comes first. Comparing `now` against whichever shape
    a cached pair has lets a stale clock still answer correctly through one
    open-or-close transition it has not itself observed."""
    if next_close < next_open:
        return now < next_close
    return next_open <= now < next_close


def _stale_clock(cached: MarketClock) -> MarketClock:
    """The live `/v2/clock` fetch failed -- fall back to the last clock this
    client saw, re-deriving `is_open` instead of trusting the stored flag,
    which the elapsed time may have made wrong."""
    now = datetime.now(UTC)
    return MarketClock(
        is_open=_is_open_between(cached.next_open, cached.next_close, now),
        next_open=cached.next_open,
        next_close=cached.next_close,
    )


@dataclass(slots=True, frozen=True)
class CalendarDay:
    trade_date: date
    open_at: datetime
    close_at: datetime


@dataclass(slots=True, frozen=True)
class RawBar:
    """One `adjustment` pass's OHLCV for one symbol/date -- not yet joined
    into a `providers.ProviderBar` (which needs both passes: `close` from
    `raw`, `adj_close` from `all`'s `close`). `AlpacaBarSource.daily_bars`
    does that join; this is the client's own, lower-level fetch shape."""

    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(slots=True, frozen=True)
class SplitAction:
    id: str
    symbol: str
    old_rate: Decimal
    new_rate: Decimal
    ex_date: date
    reverse: bool


@dataclass(slots=True, frozen=True)
class CashDividendAction:
    id: str
    symbol: str
    rate: Decimal
    ex_date: date


@dataclass(slots=True, frozen=True)
class NameChangeAction:
    id: str
    old_symbol: str
    new_symbol: str
    process_date: date


@dataclass(slots=True, frozen=True)
class CorporateActionsPage:
    splits: list[SplitAction]
    dividends: list[CashDividendAction]
    name_changes: list[NameChangeAction]
    errors: list[str] = field(default_factory=list)


class ClockSource(Protocol):
    async def get_clock(self, *, use_cache: bool = True) -> MarketClock: ...


class CalendarSource(Protocol):
    async def get_calendar(self, start: date, end: date) -> list[CalendarDay]: ...


class RawBarsSource(Protocol):
    async def get_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        adjustment: Literal["raw", "all"],
        timeframe: str = "1Day",
        feed: str = FEED_SIP,
    ) -> dict[str, list[RawBar]]: ...


class SnapshotsSource(Protocol):
    async def get_snapshots(
        self, symbols: Sequence[str], *, feed: str = FEED_IEX, attempts: int = MAX_ATTEMPTS
    ) -> list[ProviderQuote]: ...


class CorporateActionsSource(Protocol):
    async def get_corporate_actions(
        self, symbols: Sequence[str], *, types: Sequence[str], start: date, end: date
    ) -> CorporateActionsPage: ...


# The free tier refuses SIP data from the last 15 minutes, and a bare date means
# the whole day, so an end date of today would always 403. IEX / paid SIP do
# not inherit this cap.
SIP_EMBARGO = timedelta(minutes=16)


def _format_utc_z(when: datetime) -> str:
    """RFC3339 UTC with a literal `Z` suffix (Alpaca's preferred end form)."""
    utc = when.astimezone(UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond:06d}Z"


def _bars_end(end: date, *, feed: str, now: datetime | None = None) -> str:
    """Wire shape for the bars `end` query param. SIP free-tier only: when
    `end` falls on/after the embargo cutoff's NY date, send a timestamp
    below the 15-minute embargo instead of a bare date (which means
    end-of-day and 403s). Other feeds pass the bare date through."""
    if feed != FEED_SIP:
        return end.isoformat()
    cutoff = (now if now is not None else datetime.now(UTC)) - SIP_EMBARGO
    if end >= ny_date(cutoff):
        return _format_utc_z(cutoff)
    return end.isoformat()


class AlpacaClient:
    def __init__(self, key_id: str, secret_key: str) -> None:
        headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
        self._trading = build_http_client(base_url=TRADING_API_BASE_URL, headers=headers)
        self._data = build_http_client(base_url=DATA_API_BASE_URL, headers=headers)
        self._clock_cache: tuple[float, MarketClock] | None = None

    async def aclose(self) -> None:
        await self._trading.aclose()
        await self._data.aclose()

    async def get_clock(self, *, use_cache: bool = True) -> MarketClock:
        """Draws from the quotes budget, not the general one -- `quotes_poll`
        calls this every 15s tick, and freshness (N1) must never queue
        behind a slow backfill batch spending the general budget. A single
        attempt: an Alpaca outage right now falls back to the last clock
        this client saw rather than block the tick on retries, with
        `is_open` re-derived from that cached clock's `next_open`/
        `next_close` (`_is_open_between`) since the elapsed time may have
        made the cached flag itself wrong."""
        cached_entry = self._clock_cache
        if use_cache and cached_entry is not None:
            fetched_at, cached = cached_entry
            if time.monotonic() - fetched_at < CLOCK_CACHE_SECONDS:
                return cached

        try:
            response = await request(
                self._trading, "GET", "/v2/clock", rate_budget=RateBudgetName.ALPACA_QUOTES, attempts=1
            )
        except httpx.HTTPError:
            if cached_entry is None:
                raise
            return _stale_clock(cached_entry[1])

        body = response.json()
        clock = MarketClock(
            is_open=body["is_open"],
            next_open=_parse_timestamp(body["next_open"]),
            next_close=_parse_timestamp(body["next_close"]),
        )
        self._clock_cache = (time.monotonic(), clock)
        return clock

    async def get_calendar(self, start: date, end: date) -> list[CalendarDay]:
        response = await request(
            self._trading,
            "GET",
            "/v2/calendar",
            params={"start": start.isoformat(), "end": end.isoformat()},
            rate_budget=RateBudgetName.ALPACA,
        )
        return [
            CalendarDay(
                trade_date=date.fromisoformat(row["date"]),
                open_at=_combine_ny(date.fromisoformat(row["date"]), row["open"]),
                close_at=_combine_ny(date.fromisoformat(row["date"]), row["close"]),
            )
            for row in response.json()
        ]

    async def _paged(
        self, method: str, url: str, *, params: dict[str, str | int], rate_budget: RateBudgetName
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield each page's JSON body from `url` against the market-data
        host, merging `next_page_token` into `params` on every request after
        the first until Alpaca stops sending one. Shared by `get_bars` and
        `get_corporate_actions`, whose only difference is what they do with
        each page's body; page tokens are never persisted (system design
        §4, `bars_backfill`: "Page tokens are never saved")."""
        page_token: str | None = None
        while True:
            page_params = dict(params) if page_token is None else {**params, "page_token": page_token}
            response = await request(self._data, method, url, params=page_params, rate_budget=rate_budget)
            body = response.json()
            yield body
            page_token = body.get("next_page_token")
            if not page_token:
                return

    async def get_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        adjustment: Literal["raw", "all"],
        timeframe: str = "1Day",
        feed: str = FEED_SIP,
    ) -> dict[str, list[RawBar]]:
        results: dict[str, list[RawBar]] = {symbol: [] for symbol in symbols}
        params: dict[str, str | int] = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": _bars_end(end, feed=feed),
            "adjustment": adjustment,
            "feed": feed,
            "limit": BARS_PAGE_LIMIT,
        }
        async for body in self._paged(
            "GET", "/v2/stocks/bars", params=params, rate_budget=RateBudgetName.ALPACA
        ):
            for symbol, bars in (body.get("bars") or {}).items():
                bucket = results.setdefault(symbol, [])
                for raw in bars:
                    bucket.append(
                        RawBar(
                            symbol=symbol,
                            trade_date=ny_date(_parse_timestamp(raw["t"])),
                            open=Decimal(str(raw["o"])),
                            high=Decimal(str(raw["h"])),
                            low=Decimal(str(raw["l"])),
                            close=Decimal(str(raw["c"])),
                            volume=int(raw["v"]),
                        )
                    )
        return results

    async def get_snapshots(
        self, symbols: Sequence[str], *, feed: str = FEED_IEX, attempts: int = MAX_ATTEMPTS
    ) -> list[ProviderQuote]:
        """`attempts=1` (`quotes_poll`) still draws from the quotes budget
        and still goes through `request()` -- the next 15s tick is the
        retry (system design §4)."""
        params = {"symbols": ",".join(symbols), "feed": feed}
        response = await request(
            self._data,
            "GET",
            SNAPSHOTS_PATH,
            params=params,
            rate_budget=RateBudgetName.ALPACA_QUOTES,
            attempts=attempts,
        )
        body = response.json()
        quotes: list[ProviderQuote] = []
        for symbol in symbols:
            entry = body.get(symbol)
            latest_trade = entry.get("latestTrade") if entry else None
            if not latest_trade or "p" not in latest_trade or "t" not in latest_trade:
                continue
            quotes.append(
                ProviderQuote(
                    symbol=symbol,
                    price=Decimal(str(latest_trade["p"])),
                    observed_at=_parse_timestamp(latest_trade["t"]),
                    feed=feed,
                )
            )
        return quotes

    async def get_corporate_actions(
        self,
        symbols: Sequence[str],
        *,
        types: Sequence[str],
        start: date,
        end: date,
    ) -> CorporateActionsPage:
        """One malformed row never drops the rest of the page -- each row
        is parsed on its own, and a bad one is skipped and named in
        `CorporateActionsPage.errors` instead of raising."""
        splits: list[SplitAction] = []
        dividends: list[CashDividendAction] = []
        name_changes: list[NameChangeAction] = []
        errors: list[str] = []
        params: dict[str, str | int] = {
            "symbols": ",".join(symbols),
            "types": ",".join(types),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": CORPORATE_ACTIONS_PAGE_LIMIT,
        }
        async for body in self._paged(
            "GET", "/v1/corporate-actions", params=params, rate_budget=RateBudgetName.ALPACA
        ):
            actions = body.get("corporate_actions") or {}
            for row in actions.get("forward_splits", []):
                _parse_row(row, lambda r: _split_action(r, reverse=False), splits, errors, "forward_split")
            for row in actions.get("reverse_splits", []):
                _parse_row(row, lambda r: _split_action(r, reverse=True), splits, errors, "reverse_split")
            for row in actions.get("cash_dividends", []):
                _parse_row(row, _dividend_action, dividends, errors, "cash_dividend")
            for row in actions.get("name_changes", []):
                _parse_row(row, _name_change_action, name_changes, errors, "name_change")
        return CorporateActionsPage(
            splits=splits, dividends=dividends, name_changes=name_changes, errors=errors
        )


def _parse_row[T](
    row: dict[str, object],
    parse: Callable[[dict[str, object]], T],
    into: list[T],
    errors: list[str],
    action_type: str,
) -> None:
    try:
        into.append(parse(row))
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        errors.append(f"{action_type} id={row.get('id', '?')}: {exc}")


def _split_action(row: dict[str, object], *, reverse: bool) -> SplitAction:
    return SplitAction(
        id=str(_require(row, "id")),
        symbol=str(_require(row, "symbol")),
        old_rate=Decimal(str(_require(row, "old_rate"))),
        new_rate=Decimal(str(_require(row, "new_rate"))),
        ex_date=date.fromisoformat(str(_require(row, "ex_date"))),
        reverse=reverse,
    )


def _dividend_action(row: dict[str, object]) -> CashDividendAction:
    return CashDividendAction(
        id=str(_require(row, "id")),
        symbol=str(_require(row, "symbol")),
        rate=Decimal(str(_require(row, "rate"))),
        ex_date=date.fromisoformat(str(_require(row, "ex_date"))),
    )


def _name_change_action(row: dict[str, object]) -> NameChangeAction:
    return NameChangeAction(
        id=str(_require(row, "id")),
        old_symbol=str(_require(row, "old_symbol")),
        new_symbol=str(_require(row, "new_symbol")),
        process_date=date.fromisoformat(str(_require(row, "process_date"))),
    )


def _require(row: dict[str, object], key: str) -> object:
    if key not in row or row[key] is None:
        raise KeyError(key)
    return row[key]


@lru_cache
def get_alpaca_client() -> AlpacaClient | None:
    """`None` when the keys are unset -- callers that are job handlers never
    see that case (`JobSpec.requires_keys` already turned it into a
    `config_missing` run before the handler body runs); `marketdata.py`
    does see it, for `/status` with no keys configured (N4)."""
    settings = get_settings()
    if not settings.alpaca_key_id or not settings.alpaca_secret_key:
        return None
    return AlpacaClient(settings.alpaca_key_id, settings.alpaca_secret_key)


def reset_alpaca_client() -> None:
    """Test-only: clear the cached client between test cases that change
    `ALPACA_KEY_ID`/`ALPACA_SECRET_KEY`."""
    get_alpaca_client.cache_clear()


def require_alpaca_client() -> AlpacaClient:
    """The one place a job handler gets its `AlpacaClient` -- `requires_keys`
    on the `JobSpec` already turned a missing key into a `config_missing`
    run before the handler body runs, so the `None` case is unreachable
    here; the assert documents that instead of every handler repeating
    `get_alpaca_client()` plus its own copy of this comment."""
    client = get_alpaca_client()
    assert client is not None, "requires_keys already gated this job"
    return client


__all__ = [
    "AlpacaClient",
    "CalendarDay",
    "CalendarSource",
    "CashDividendAction",
    "ClockSource",
    "CorporateActionsPage",
    "CorporateActionsSource",
    "NameChangeAction",
    "RawBarsSource",
    "SnapshotsSource",
    "SplitAction",
    "get_alpaca_client",
    "require_alpaca_client",
    "reset_alpaca_client",
]
