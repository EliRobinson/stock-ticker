"""Shared httpx client factory: timeouts, retry policy, and per-source rate
budgets (system design §4, "HTTP rules").

Every provider client (Alpaca, SEC EDGAR, the Wikipedia fetch) should call
`build_http_client()` for its `httpx.AsyncClient` and `request()` for every
call it makes, naming the rate budget it draws from.
"""

from __future__ import annotations

import asyncio
import email.utils
import math
import random
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=30.0)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
RETRY_AFTER_CAP_SECONDS = 60.0


class RateBudgetName(StrEnum):
    ALPACA_QUOTES = "alpaca_quotes"
    ALPACA = "alpaca"
    SEC = "sec"
    WIKIPEDIA = "wikipedia"


@dataclass(frozen=True, slots=True)
class RateBudget:
    name: RateBudgetName
    capacity: int
    per_seconds: float


RATE_BUDGETS: dict[RateBudgetName, RateBudget] = {
    RateBudgetName.ALPACA_QUOTES: RateBudget(RateBudgetName.ALPACA_QUOTES, capacity=40, per_seconds=60.0),
    RateBudgetName.ALPACA: RateBudget(RateBudgetName.ALPACA, capacity=100, per_seconds=60.0),
    RateBudgetName.SEC: RateBudget(RateBudgetName.SEC, capacity=5, per_seconds=1.0),
    RateBudgetName.WIKIPEDIA: RateBudget(RateBudgetName.WIKIPEDIA, capacity=10, per_seconds=60.0),
}


class TokenBucket:
    """A simple async token bucket. One instance per rate budget, shared by
    every caller drawing from that budget within the process."""

    def __init__(self, capacity: int, per_seconds: float) -> None:
        self._capacity = float(capacity)
        self._refill_rate = capacity / per_seconds
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._refill_rate)


@lru_cache
def get_rate_budget(name: RateBudgetName) -> TokenBucket:
    budget = RATE_BUDGETS[name]
    return TokenBucket(budget.capacity, budget.per_seconds)


def reset_rate_budgets() -> None:
    """Test-only: clear cached token buckets between test cases."""
    get_rate_budget.cache_clear()


class RetryableStatusError(httpx.HTTPStatusError):
    """A 429/5xx we've decided to retry. Subclasses `httpx.HTTPStatusError`
    (not a bare `Exception`) so it carries the request/response pair the
    same way `response.raise_for_status()` would, for any caller that
    catches the httpx type -- `retry_after` is the only thing we add."""

    def __init__(self, response: httpx.Response) -> None:
        self.retry_after = _parse_retry_after(response.headers.get("retry-after"))
        super().__init__(
            f"retryable status {response.status_code} from {response.request.url}",
            request=response.request,
            response=response,
        )


def _parse_retry_after(value: str | None) -> float | None:
    """A `Retry-After` we've already decided to honor, clamped to
    `[0, RETRY_AFTER_CAP_SECONDS]` -- a misbehaving or malicious upstream
    can otherwise send an unbounded or non-finite (`inf`/`nan`) value and
    stall the retry loop far past `BACKOFF_CAP_SECONDS`."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        seconds = None
    if seconds is None:
        try:
            dt = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = (dt - dt.now(dt.tzinfo)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return min(RETRY_AFTER_CAP_SECONDS, max(0.0, seconds))


def _wait(retry_state: RetryCallState) -> float:
    attempt = retry_state.attempt_number
    cap = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    # Full jitter (not "equal jitter"): sample uniformly from [0, cap]
    # rather than [cap/2, cap] -- spreads retries out more and is what
    # AWS's backoff writeup recommends as the default.
    jittered = random.uniform(0.0, cap)
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, RetryableStatusError) and exc.retry_after is not None:
        return max(jittered, exc.retry_after)
    return jittered


def build_http_client(
    *,
    base_url: str = "",
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    rate_budget: RateBudgetName,
    **kwargs: object,
) -> httpx.Response:
    """Issue one HTTP request under the named rate budget, with the shared
    retry policy: connection errors, 429, and 5xx retry with exponential
    backoff and full jitter (1s base, 30s cap, 4 attempts total), honoring
    `Retry-After`. Any other 4xx fails immediately. `rate_budget` is
    required -- every provider call belongs to exactly one budget."""
    bucket = get_rate_budget(rate_budget)

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((httpx.TransportError, RetryableStatusError)),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=_wait,
        reraise=True,
    ):
        with attempt:
            await bucket.acquire()
            response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
            if response.status_code in RETRYABLE_STATUS_CODES:
                raise RetryableStatusError(response)
            response.raise_for_status()
            return response
    raise AssertionError("unreachable: AsyncRetrying always raises or returns")
