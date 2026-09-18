"""Pricing math, and the stream encoder's protocol-order rules."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from stockticker.ai.pricing import PRICES, TokenUsage, cost_usd, price_for, worst_case_cost_usd
from stockticker.ai.stream import (
    DONE,
    UI_MESSAGE_STREAM_HEADERS,
    UNFINISHED_TOOL_ERROR,
    StreamStateError,
    UIMessageStreamEncoder,
    sse,
)


def test_sonnet_5_prices_each_token_kind_separately() -> None:
    price = PRICES["claude-sonnet-5"]
    usage = TokenUsage(
        input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # $2 input, $2.50 cache write (1.25x), $0.20 cache read (0.1x), $10 output.
    assert cost_usd(price, usage) == Decimal("14.700000")


def test_cost_rounds_up_to_the_micro_dollar() -> None:
    assert cost_usd(PRICES["claude-sonnet-5"], TokenUsage(input_tokens=1)) == Decimal("0.000002")


def test_worst_case_prices_all_input_as_cache_writes_plus_full_output() -> None:
    price = PRICES["claude-sonnet-5"]
    assert worst_case_cost_usd(price, max_input_tokens=100_000, max_output_tokens=8_192) == Decimal(
        "0.331920"
    )


def test_fable_5_1_cache_reads_are_a_quarter_dollar() -> None:
    assert PRICES["claude-fable-5-1"].cache_read == Decimal("0.25")


def test_unknown_model_has_no_price() -> None:
    assert price_for("claude-unknown") is None


# --- encoder ------------------------------------------------------------------


def test_sse_framing_matches_json_stringify() -> None:
    assert sse({"type": "text-delta", "id": "t", "delta": "é \n"}) == (
        'data: {"type":"text-delta","id":"t","delta":"é \\n"}\n\n'
    )


def test_headers() -> None:
    assert UI_MESSAGE_STREAM_HEADERS == {
        "x-vercel-ai-ui-message-stream": "v1",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    }


def test_fail_closes_open_text_and_tools_before_error_and_finish() -> None:
    encoder = UIMessageStreamEncoder("m")
    encoder.start()
    encoder.start_step()
    encoder.text_start("t1")
    encoder.tool_input_available("c1", "run_sql", {"sql": "SELECT 1"})
    encoder.tool_input_available("c2", "run_sql", {"sql": "SELECT 2"})
    events = encoder.fail("Boom.")
    parts = [json.loads(e.removeprefix("data: ")) for e in events[:-1]]
    assert parts == [
        {"type": "text-end", "id": "t1"},
        {"type": "tool-output-error", "toolCallId": "c1", "errorText": UNFINISHED_TOOL_ERROR},
        {"type": "tool-output-error", "toolCallId": "c2", "errorText": UNFINISHED_TOOL_ERROR},
        {"type": "error", "errorText": "Boom."},
        {"type": "finish", "finishReason": "error"},
    ]
    assert events[-1] == DONE
    assert encoder.closed


def test_fail_before_start_still_sends_start() -> None:
    events = UIMessageStreamEncoder("m").fail("Off.")
    assert [json.loads(e.removeprefix("data: "))["type"] for e in events[:-1]] == ["start", "error", "finish"]


@pytest.mark.parametrize(
    "misuse",
    [
        lambda e: e.start_step(),  # before start
        lambda e: (e.start(), e.text_start("t")),  # outside a step
        lambda e: (e.start(), e.start_step(), e.text_delta("t", "x")),  # unopened text
        lambda e: (e.start(), e.start_step(), e.tool_output_available("c", {})),  # unknown call
        lambda e: (e.start(), e.start_step(), e.text_start("t"), e.finish_step()),  # open text
        lambda e: (e.start(), e.start_step(), e.tool_input_available("c", "run_sql", {}), e.finish_step()),
        lambda e: (e.start(), e.start_step(), e.finish()),  # finish inside a step
        lambda e: (e.start(), e.finish(), e.start_step()),  # after finish
        lambda e: (e.start(), e.start()),
    ],
)
def test_out_of_order_parts_are_bugs(misuse) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(StreamStateError):
        misuse(UIMessageStreamEncoder("m"))
