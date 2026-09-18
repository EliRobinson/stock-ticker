"""Review-round cases for the loop: spend settled when a call dies before
`message_start`, the input budget on the first call, the wall clock across
every await, and a producer that crashes outright."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

from ai_fakes import (
    MODEL,
    ConnectionDrop,
    FakeExecutor,
    MemoryLedger,
    ScriptedAnthropic,
    answer_text,
    error_texts,
    make_deps,
    part_types,
    text_answer,
    user,
)

from stockticker.ai.convert import UIMessage
from stockticker.ai.loop import ChatDeps, Limits, PromptContext
from stockticker.ai.pricing import PRICES, TokenUsage, cost_usd
from stockticker.ai.stream import never_disconnects, until_disconnected


async def run(deps: ChatDeps, messages: list[UIMessage] | None = None) -> str:
    return await answer_text(deps, messages)


# --- #3 spend before message_start ------------------------------------------------


async def test_a_connection_drop_before_message_start_is_charged_the_input_bound() -> None:
    ledger = MemoryLedger()
    out = await run(make_deps(ScriptedAnthropic(ConnectionDrop()), ledger=ledger))
    assert error_texts(out) == ["Anthropic could not be reached. Try again."]
    (row,) = ledger.rows
    assert row.state == "recorded"
    assert row.usage == TokenUsage()
    assert row.cost_usd > 0
    # The input bound, at the plain input rate (not the cache-write rate).
    bound = int(row.cost_usd / PRICES[MODEL].input * 1_000_000)
    assert cost_usd(PRICES[MODEL], TokenUsage(input_tokens=bound)) == row.cost_usd


async def test_a_refusal_at_stream_open_costs_nothing() -> None:
    from ai_fakes import HttpError

    ledger = MemoryLedger()
    await run(make_deps(ScriptedAnthropic(HttpError(400, "invalid_request_error")), ledger=ledger))
    (row,) = ledger.rows
    assert row.cost_usd == Decimal(0)


# --- #4 the first call fits the input budget -----------------------------------------


def _conversation(turns: int, filler: int) -> list[UIMessage]:
    messages: list[UIMessage] = []
    for i in range(turns):
        messages.append(user(f"question {i} " + "x" * filler, f"u{i}"))
        messages.append(
            UIMessage(id=f"a{i}", role="assistant", parts=[{"type": "text", "text": f"answer {i}"}])
        )
    messages.append(user("the latest question", "last"))
    return messages


async def test_old_history_is_dropped_so_the_first_call_fits_the_input_budget() -> None:
    anthropic = ScriptedAnthropic(text_answer("ok"))
    limits = Limits(max_input_tokens=20_000)
    await run(make_deps(anthropic, limits=limits), _conversation(turns=10, filler=3_000))
    sent = anthropic.requests[0]["messages"]
    assert len(json.dumps(anthropic.requests[0]).encode()) < limits.max_input_tokens
    assert sent[0]["role"] == "user"
    assert sent[-1]["content"] == [{"type": "text", "text": "the latest question"}]
    assert 1 < len(sent) < 21


async def test_a_message_too_long_for_the_budget_gets_its_own_error() -> None:
    anthropic = ScriptedAnthropic()
    out = await run(make_deps(anthropic, limits=Limits(max_input_tokens=5_000)), [user("x" * 20_000)])
    assert error_texts(out) == ["This message is too long to answer. Shorten it and send it again."]
    assert anthropic.requests == []


# --- #5 the wall clock covers every await -------------------------------------------


async def test_the_wall_clock_covers_loading_the_prompt_context() -> None:
    async def slow_context() -> PromptContext:
        await asyncio.sleep(5)
        raise AssertionError("unreachable")

    out = await run(
        make_deps(ScriptedAnthropic(), limits=Limits(wall_seconds=0.1), load_context=slow_context)
    )
    assert error_texts(out) == ["Stopped after 0.1 s without a final answer. Ask a narrower question."]


async def test_the_wall_clock_covers_the_spend_reservation() -> None:
    class SlowLedger(MemoryLedger):
        async def reserve(self, **kwargs: Any) -> int:
            await asyncio.sleep(5)
            return await super().reserve(**kwargs)

    out = await run(make_deps(ScriptedAnthropic(), ledger=SlowLedger(), limits=Limits(wall_seconds=0.1)))
    assert error_texts(out) == ["Stopped after 0.1 s without a final answer. Ask a narrower question."]


async def test_the_wall_clock_covers_opening_the_model_stream() -> None:
    class SlowToOpen(ScriptedAnthropic):
        async def _handle(self, request: Any) -> Any:
            await asyncio.sleep(5)
            return await super()._handle(request)

    ledger = MemoryLedger()
    out = await run(make_deps(SlowToOpen(text_answer("ok")), ledger=ledger, limits=Limits(wall_seconds=0.1)))
    assert error_texts(out) == ["Stopped after 0.1 s without a final answer. Ask a narrower question."]
    (row,) = ledger.rows
    assert row.state == "recorded"


# --- #10 a producer that crashes still finishes the stream -----------------------------


async def test_a_crashing_producer_still_sends_error_finish_and_done() -> None:
    async def producer(emit: Any) -> None:
        await emit('data: {"type":"start","messageId":"m"}\n\n')
        raise RuntimeError("bug")

    out = "".join([c async for c in until_disconnected(producer, never_disconnects)])
    assert part_types(out) == ["start", "error", "finish", "[DONE]"]


async def test_tool_failures_never_end_the_answer() -> None:
    from ai_fakes import tool_call

    class Exploding(FakeExecutor):
        async def execute(self, sql: str) -> Any:
            raise KeyError("boom")

    anthropic = ScriptedAnthropic(
        tool_call("t1", "run_sql", {"sql": "SELECT name FROM ai.companies", "purpose": "p"}),
        text_answer("Could not run it."),
    )
    out = await run(make_deps(anthropic, Exploding()))
    assert "tool-output-error" in part_types(out)
    assert part_types(out)[-2:] == ["finish", "[DONE]"]
    assert error_texts(out) == []
