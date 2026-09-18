"""Golden streams: the exact bytes `/api/v1/chat` sends on each path
(system design §6, "Response"). The model is a scripted Anthropic transport
and Postgres a fake executor, so every byte comes from the real loop and
encoder. Regenerate after a deliberate protocol change with
`UPDATE_GOLDEN=1 uv run pytest tests/unit/test_ai_stream_golden.py`, and
review the diff."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from ai_fakes import (
    QUESTION,
    TOP_SQL,
    FakeExecutor,
    MemoryLedger,
    ScriptedAnthropic,
    answer_text,
    make_deps,
    message_start,
    normal_answer_script,
    part_types,
    result,
    stream_error,
    text_answer,
    text_block_open,
    tool_call,
    user,
)

from stockticker.ai.loop import ChatDeps, Limits

GOLDEN = Path(__file__).parent / "golden"


async def render(deps: ChatDeps, question: str = QUESTION) -> str:
    return await answer_text(deps, [user(question)], "msg-golden")


def check(name: str, body: str) -> None:
    path = GOLDEN / f"{name}.sse"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(body)
    assert body == path.read_text(), f"{name} differs from {path}; see the module docstring"


async def test_normal_answer_with_a_table() -> None:
    anthropic, executor = normal_answer_script()
    body = await render(make_deps(anthropic, executor))
    check("normal_answer_with_table", body)
    assert part_types(body) == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "tool-input-available",
        "tool-output-available",
        "finish-step",
        "start-step",
        "tool-input-available",
        "tool-output-available",
        "data-view",
        "finish-step",
        "start-step",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
        "[DONE]",
    ]


async def test_tool_error_then_recovery() -> None:
    anthropic = ScriptedAnthropic(
        tool_call("toolu_01", "run_sql", {"sql": "SELECT * FROM pg_catalog.pg_authid", "purpose": "Look"}),
        text_answer("I can only read the ai views, so I cannot answer that."),
    )
    body = await render(make_deps(anthropic, FakeExecutor()), "List the database roles.")
    check("tool_error", body)
    assert part_types(body) == [
        "start",
        "start-step",
        "tool-input-available",
        "tool-output-error",
        "finish-step",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
        "[DONE]",
    ]


async def test_model_error_mid_text() -> None:
    anthropic = ScriptedAnthropic(message_start() + text_block_open(0, "Apple is") + stream_error())
    body = await render(make_deps(anthropic))
    check("model_error_mid_text", body)
    assert part_types(body) == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "error",
        "finish",
        "[DONE]",
    ]


async def test_spend_limit_reached_before_the_next_call() -> None:
    # The first call fits under the limit; the usage it reports (100k input
    # tokens, $0.20 at Sonnet 5 prices) leaves no room for the second.
    anthropic = ScriptedAnthropic(
        tool_call(
            "toolu_01", "run_sql", {"sql": TOP_SQL, "purpose": "Rank by market cap"}, input_tokens=100_000
        ),
    )
    executor = FakeExecutor(result([("name", "text"), ("market_cap", "numeric")], [("Apple Inc.", 3.1e12)]))
    ledger = MemoryLedger(spent=Decimal("4.80"))
    body = await render(make_deps(anthropic, executor, ledger=ledger))
    check("spend_limit_reached", body)
    assert part_types(body) == [
        "start",
        "start-step",
        "tool-input-available",
        "tool-output-available",
        "finish-step",
        "error",
        "finish",
        "[DONE]",
    ]
    assert "AI spend limit reached ($5.00). Raise AI_SPEND_LIMIT_USD to continue." in body


async def test_wall_clock_exhausted_while_a_tool_runs() -> None:
    anthropic = ScriptedAnthropic(
        tool_call("toolu_01", "run_sql", {"sql": TOP_SQL, "purpose": "Rank"}, lead="Querying."),
    )
    executor = FakeExecutor(result([("name", "text")], [("Apple",)]), delay=5)
    deps = make_deps(anthropic, executor, limits=Limits(wall_seconds=0.2))
    body = await render(deps)
    check("wall_clock_exhausted", body)
    assert part_types(body) == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "tool-input-available",
        "tool-output-error",
        "error",
        "finish",
        "[DONE]",
    ]
    assert executor.cancelled.is_set()


async def test_no_key() -> None:
    body = await render(make_deps(None))
    check("no_key", body)
    assert "AI is off. ANTHROPIC_API_KEY is not set." in body
