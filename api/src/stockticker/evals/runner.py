"""Runs the golden cases against a running API and grades each answer.

The runner is the only piece with side effects, and each one sits behind a
small protocol so the tests can fake it:

- `AskApi`: the running app over HTTP. `/api/v1/chat` answers, `/api/v1/notes`
  seeds and removes a case's Notes, `/api/v1/status` reports spend.
- `ReferenceSource`: the reference SQL, run as `ai_reader` through the same
  guard the model's queries go through.
- `UsageSource`: the `ai_usage` ledger rows each case added, which is where
  the per-case tokens and cost come from.
- `Judge`: the LLM judge (`judge.py`).

A case runs only when its references hold (`expect: rows` found rows,
`expect: empty` found none); otherwise it is blocked and costs nothing.
Before each case the runner checks the run's budget, so a run stops short
rather than going over it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

import anthropic
import httpx

from stockticker.ai.spend import SpendGateError
from stockticker.evals.cases import Case, SeedNote
from stockticker.evals.graders import CheckResult, ReferenceRows, run_checks
from stockticker.evals.judge import JudgeError, JudgeResult, Verdict
from stockticker.evals.transcript import Transcript, TranscriptBuilder

CHAT_TIMEOUT_SECONDS = 150.0
MIN_CASE_ESTIMATE_USD = Decimal("0.05")
"""What the budget guard assumes the next case may cost before any case has
run. After that it uses 1.5x the most expensive case so far, if larger."""


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class UsageRow:
    model: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int
    cost_usd: Decimal

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


@dataclass(frozen=True)
class Spend:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    calls: int = 0

    def __add__(self, other: Spend) -> Spend:
        return Spend(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
            self.calls + other.calls,
        )

    @classmethod
    def of(cls, rows: Sequence[UsageRow]) -> Spend:
        return cls(
            input_tokens=sum(row.total_input_tokens for row in rows),
            output_tokens=sum(row.output_tokens for row in rows),
            cost_usd=sum((row.cost_usd for row in rows), Decimal(0)),
            calls=len(rows),
        )


@dataclass
class CaseResult:
    case: Case
    outcome: Outcome
    reason: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    transcript: Transcript | None = None
    answer_spend: Spend = field(default_factory=Spend)
    judge_spend: Spend = field(default_factory=Spend)

    @property
    def spend(self) -> Spend:
        return self.answer_spend + self.judge_spend

    @property
    def failures(self) -> list[str]:
        failed = [f"{c.name}: {c.detail}".rstrip(": ") for c in self.checks if not c.passed]
        failed += [f"judge {v.criterion}: {v.reason}" for v in self.verdicts if not v.passed]
        return failed


@dataclass(frozen=True)
class ApiStatus:
    spend_usd: Decimal
    limit_usd: Decimal
    enabled: bool
    listings_done: int | None
    listings_total: int | None


class AskApi(Protocol):
    async def ask(self, question: str) -> Transcript: ...

    async def put_note(self, note_id: uuid.UUID, note: SeedNote) -> None: ...

    async def delete_note(self, note_id: uuid.UUID) -> None: ...

    async def status(self) -> ApiStatus: ...


class ReferenceSource(Protocol):
    async def rows(self, sql: str) -> list[dict[str, Any]]: ...


class UsageSource(Protocol):
    async def watermark(self) -> int: ...

    async def since(self, watermark: int) -> list[UsageRow]: ...


class CaseJudge(Protocol):
    model: str

    async def grade(self, question: str, transcript: Transcript, criteria: Sequence[Any]) -> JudgeResult: ...


# --- the HTTP client ---------------------------------------------------------------------


class HttpAskApi:
    """`AskApi` over HTTP. `host_header` is for calling the API by a compose
    service name: its TrustedHost middleware accepts only 127.0.0.1 and
    localhost."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @classmethod
    @asynccontextmanager
    async def connect(cls, base_url: str, host_header: str | None = None) -> AsyncIterator[HttpAskApi]:
        headers = {"Host": host_header} if host_header else {}
        timeout = httpx.Timeout(CHAT_TIMEOUT_SECONDS, connect=10.0)
        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
            yield cls(client)

    async def ask(self, question: str) -> Transcript:
        body = {
            "id": f"eval-{uuid.uuid4().hex[:12]}",
            "messages": [
                {"id": "q1", "role": "user", "parts": [{"type": "text", "text": question}]},
            ],
            "trigger": "submit-message",
            "messageId": None,
        }
        builder = TranscriptBuilder()
        async with self._client.stream("POST", "/api/v1/chat", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                builder.feed_line(line)
        return builder.finish()

    async def put_note(self, note_id: uuid.UUID, note: SeedNote) -> None:
        response = await self._client.put(f"/api/v1/notes/{note_id}", json=note.model_dump(mode="json"))
        response.raise_for_status()

    async def delete_note(self, note_id: uuid.UUID) -> None:
        response = await self._client.delete(f"/api/v1/notes/{note_id}")
        response.raise_for_status()

    async def status(self) -> ApiStatus:
        response = await self._client.get("/api/v1/status")
        response.raise_for_status()
        return parse_status(response.json())


def parse_status(payload: dict[str, Any]) -> ApiStatus:
    ai = payload.get("ai") or {}
    backfill = payload.get("backfill") or {}
    return ApiStatus(
        spend_usd=Decimal(str(ai.get("spend_usd", 0))),
        limit_usd=Decimal(str(ai.get("limit_usd", 0))),
        enabled=bool(ai.get("enabled")),
        listings_done=backfill.get("listings_done"),
        listings_total=backfill.get("listings_total"),
    )


# --- the run -------------------------------------------------------------------------------


_SYMBOL = re.compile(r"^[A-Z][A-Z.]{0,9}$")


def backfilled_sql(symbols: Sequence[str]) -> str:
    """Which of `symbols` have full price history: a bar on the first Trading
    Day any Listing has, and on the latest one."""
    for symbol in symbols:
        if not _SYMBOL.match(symbol):
            raise ValueError(f"not a ticker: {symbol!r}")
    listed = ", ".join(f"'{symbol}'" for symbol in symbols)
    return (
        "WITH bounds AS (SELECT min(trade_date) AS first_day, max(trade_date) AS last_day "
        "FROM ai.daily_prices) "
        "SELECT p.symbol FROM ai.daily_prices p CROSS JOIN bounds b "
        f"WHERE p.symbol IN ({listed}) "
        "GROUP BY p.symbol, b.first_day, b.last_day "
        "HAVING min(p.trade_date) = b.first_day AND max(p.trade_date) = b.last_day"
    )


@dataclass
class Runner:
    api: AskApi
    references: ReferenceSource
    usage: UsageSource
    judge: CaseJudge | None
    budget_usd: Decimal
    backfilled_only: bool = False
    spent_usd: Decimal = Decimal(0)
    stopped: str = ""

    async def run(self, cases: Sequence[Case]) -> list[CaseResult]:
        backfilled = await self._backfilled(cases) if self.backfilled_only else None
        results: list[CaseResult] = []
        for case in cases:
            result = await self.run_case(case, backfilled, results)
            self.spent_usd += result.spend.cost_usd
            results.append(result)
        return results

    async def run_case(
        self, case: Case, backfilled: set[str] | None, done: Sequence[CaseResult]
    ) -> CaseResult:
        if backfilled is not None:
            if case.needs_full_backfill:
                return CaseResult(case, Outcome.SKIPPED, "needs every Listing backfilled")
            missing = [symbol for symbol in case.companies if symbol not in backfilled]
            if missing:
                return CaseResult(case, Outcome.SKIPPED, f"not backfilled yet: {', '.join(missing)}")
        references, blocked = await self._references(case)
        if blocked:
            return CaseResult(case, Outcome.BLOCKED, blocked)
        estimate = max([MIN_CASE_ESTIMATE_USD, *(r.spend.cost_usd * Decimal("1.5") for r in done)])
        if self.stopped or self.spent_usd + estimate > self.budget_usd:
            self.stopped = self.stopped or (
                f"budget: ${self.spent_usd:.4f} spent, next case may cost ${estimate:.4f}, "
                f"budget ${self.budget_usd:.2f}"
            )
            return CaseResult(case, Outcome.SKIPPED, self.stopped)

        watermark = await self.usage.watermark()
        result = CaseResult(case, Outcome.ERROR)
        try:
            result.transcript = await self._ask_with_notes(case)
        except (httpx.HTTPError, ValueError) as error:
            result.reason = f"{type(error).__name__}: {error}"
        else:
            result.checks = run_checks(case.checks, result.transcript, references)
            if case.judge and self.judge is not None:
                result.verdicts = await self._judge(case, result.transcript)
            passed = all(c.passed for c in result.checks) and all(v.passed for v in result.verdicts)
            result.outcome = Outcome.PASS if passed else Outcome.FAIL
        rows = await self.usage.since(watermark)
        judge_model = self.judge.model if self.judge is not None else None
        result.answer_spend = Spend.of([row for row in rows if row.model != judge_model])
        result.judge_spend = Spend.of([row for row in rows if row.model == judge_model])
        return result

    async def _backfilled(self, cases: Sequence[Case]) -> set[str]:
        symbols = sorted({symbol for case in cases for symbol in case.companies})
        if not symbols:
            return set()
        return {str(row["symbol"]) for row in await self.references.rows(backfilled_sql(symbols))}

    async def _references(self, case: Case) -> tuple[ReferenceRows, str]:
        computed: ReferenceRows = {}
        for name, reference in case.references.items():
            try:
                rows = await self.references.rows(reference.sql)
            except Exception as error:
                return computed, f"reference {name} failed: {error}"
            if reference.expect == "rows" and not rows:
                return computed, f"reference {name} returned no rows; the data is not loaded"
            if reference.expect == "empty" and rows:
                return computed, f"reference {name} expected no rows but found {len(rows)}"
            computed[name] = rows
        return computed, ""

    async def _ask_with_notes(self, case: Case) -> Transcript:
        seeded: list[uuid.UUID] = []
        try:
            for note in case.setup.notes:
                note_id = uuid.uuid4()
                await self.api.put_note(note_id, note)
                seeded.append(note_id)
            return await self.api.ask(case.question)
        finally:
            for note_id in seeded:
                await self.api.delete_note(note_id)

    async def _judge(self, case: Case, transcript: Transcript) -> list[Verdict]:
        assert self.judge is not None
        try:
            graded = await self.judge.grade(case.question, transcript, case.judge)
        except (JudgeError, anthropic.APIError, SpendGateError) as error:
            return [Verdict(criterion, False, f"judge error: {error}") for criterion in case.judge]
        return graded.verdicts
