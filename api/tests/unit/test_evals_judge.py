"""The LLM judge: its prompt, its reply parser, and its spend accounting. The
Anthropic client is a fake; the ledger is the in-memory one the Ask tests use."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from ai_fakes import MemoryLedger
from anthropic.resources.messages import AsyncMessages

from stockticker.ai.pricing import TokenUsage, cost_usd, price_for
from stockticker.ai.spend import SpendLimitReached
from stockticker.evals.judge import (
    CRITERIA,
    JUDGE_MODEL,
    Judge,
    JudgeError,
    build_prompt,
    evidence,
    parse_verdicts,
)
from stockticker.evals.transcript import ToolCall, Transcript

PRICE = price_for(JUDGE_MODEL)
assert PRICE is not None


def transcript() -> Transcript:
    return Transcript(
        texts=["APA fell 84.9% from 2020-02-19 to 2020-03-23."],
        tool_calls=[
            ToolCall(
                "c1",
                "run_sql",
                {"sql": "SELECT symbol, pct_change FROM ai.returns_between(...)", "purpose": "Rank"},
                output={"columns": [["symbol", "text"]], "rows": [["APA", -84.86]]},
            ),
            ToolCall(
                "c2",
                "run_sql",
                {"sql": "SELECT nope", "purpose": "Retry"},
                error="column nope does not exist",
            ),
        ],
        finish_reason="stop",
        done=True,
    )


class FakeMessages:
    def __init__(self, reply: str | Exception, usage: TokenUsage) -> None:
        self.reply = reply
        self.usage = usage
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.reply)],
            usage=SimpleNamespace(
                input_tokens=self.usage.input_tokens,
                cache_creation_input_tokens=None,
                cache_read_input_tokens=None,
                output_tokens=self.usage.output_tokens,
            ),
        )


def judge(
    reply: str | Exception, ledger: MemoryLedger, usage: TokenUsage | None = None
) -> tuple[Judge, FakeMessages]:
    messages = FakeMessages(reply, usage or TokenUsage(input_tokens=1200, output_tokens=90))
    assert PRICE is not None
    return (
        Judge(
            client=SimpleNamespace(messages=messages),
            ledger=ledger,
            price=PRICE,
            spend_limit_usd=Decimal("5"),
            daily_token_budget=2_000_000,
            day_start=lambda: datetime(2026, 9, 18, 4, tzinfo=UTC),
        ),
        messages,
    )


def test_evidence_lists_each_query_its_result_or_error_and_is_capped() -> None:
    text = evidence(transcript())
    assert "run_sql purpose: Rank" in text
    assert '"APA",-84.86' in text
    assert "error: column nope does not exist" in text
    assert evidence(Transcript()) == "(the assistant called no tools)"
    cut = evidence(transcript(), limit=40)
    assert cut.endswith("[evidence cut]")
    assert len(cut.encode()) <= 40 + len("\n...[evidence cut]")


def test_the_prompt_has_the_question_answer_evidence_and_only_the_asked_criteria() -> None:
    prompt = build_prompt("Steepest COVID decline?", transcript(), ["no_invented_numbers"])
    assert "<question>\nSteepest COVID decline?\n</question>" in prompt
    assert "APA fell 84.9%" in prompt
    assert "<evidence>" in prompt
    assert CRITERIA["no_invented_numbers"] in prompt
    assert CRITERIA["interpretation_stated"] not in prompt
    assert '"no_invented_numbers": {"reason"' in prompt


def test_parse_verdicts_reads_the_json_even_inside_prose() -> None:
    raw = 'Here you go:\n{"no_invented_numbers": {"reason": "84.9 rounds 84.86.", "verdict": "PASS"}}'
    [verdict] = parse_verdicts(raw, ["no_invented_numbers"])
    assert verdict.passed
    assert verdict.reason == "84.9 rounds 84.86."


@pytest.mark.parametrize(
    "raw",
    [
        "no json at all",
        '{"no_invented_numbers": {"reason": "x"',
        '{"interpretation_stated": {"verdict": "pass"}}',
        '{"no_invented_numbers": {"verdict": "maybe"}}',
        '{"no_invented_numbers": "pass"}',
    ],
)
def test_parse_verdicts_rejects_a_reply_without_a_clear_label(raw: str) -> None:
    with pytest.raises(JudgeError):
        parse_verdicts(raw, ["no_invented_numbers"])


async def test_grade_reserves_then_settles_the_real_cost_in_the_ledger() -> None:
    ledger = MemoryLedger()
    reply = '{"no_invented_numbers": {"reason": "All from the tools.", "verdict": "pass"}}'
    grader, messages = judge(reply, ledger)
    result = await grader.grade("Q?", transcript(), ["no_invented_numbers"])
    assert [v.passed for v in result.verdicts] == [True]
    assert messages.requests[0]["model"] == JUDGE_MODEL
    accepted = set(inspect.signature(AsyncMessages.create).parameters)
    assert set(messages.requests[0]) <= accepted, "the judge sends a parameter the SDK does not take"
    [row] = ledger.rows
    assert row.model == JUDGE_MODEL
    assert row.state == "recorded"
    assert PRICE is not None
    assert row.cost_usd == cost_usd(PRICE, TokenUsage(input_tokens=1200, output_tokens=90)) == result.cost_usd
    worst_case, _ = ledger.gates[0]
    assert worst_case > row.cost_usd


async def test_a_failed_call_is_settled_at_its_worst_case() -> None:
    ledger = MemoryLedger()
    grader, _ = judge(RuntimeError("network down"), ledger)
    with pytest.raises(RuntimeError):
        await grader.grade("Q?", transcript(), ["no_invented_numbers"])
    [row] = ledger.rows
    worst_case, _ = ledger.gates[0]
    assert row.state == "recorded"
    assert row.cost_usd == worst_case


async def test_the_spend_cap_stops_the_judge_before_any_call() -> None:
    ledger = MemoryLedger(spent=Decimal("4.999999"))
    grader, messages = judge("{}", ledger)
    with pytest.raises(SpendLimitReached):
        await grader.grade("Q?", transcript(), ["no_invented_numbers"])
    assert messages.requests == []
