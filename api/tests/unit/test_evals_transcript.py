"""The eval stream parser, read against the recorded golden streams and
against a stream the real Ask loop produces."""

from __future__ import annotations

from pathlib import Path

import pytest
from ai_fakes import answer_text, make_deps, normal_answer_script, user

from stockticker.evals.transcript import StreamParseError, TranscriptBuilder, parse_stream

GOLDEN = Path(__file__).parent / "golden"


def golden(name: str) -> str:
    return (GOLDEN / f"{name}.sse").read_text()


def test_a_normal_answer_keeps_text_tools_and_the_table() -> None:
    t = parse_stream(golden("normal_answer_with_table"))
    assert t.completed
    assert t.steps == 3
    assert t.text.startswith("Let me check.")
    assert [call.name for call in t.tool_calls] == ["run_sql", "show_table"]
    assert t.sql_calls[0].succeeded
    assert "market_caps" in (t.sql_calls[0].sql or "")
    assert [view["kind"] for view in t.views] == ["table"]
    assert t.views[0]["rows"][0]["name"] == "Apple Inc."


def test_a_tool_error_is_kept_on_its_call() -> None:
    t = parse_stream(golden("tool_error"))
    assert t.completed
    call = t.sql_calls[0]
    assert not call.succeeded
    assert call.error is not None and "pg_catalog" in call.error


@pytest.mark.parametrize(
    "name", ["spend_limit_reached", "wall_clock_exhausted", "model_error_mid_text", "no_key"]
)
def test_an_error_part_means_the_answer_did_not_complete(name: str) -> None:
    t = parse_stream(golden(name))
    assert t.done
    assert t.finish_reason == "error"
    assert t.error
    assert not t.completed


async def test_the_real_loop_stream_round_trips() -> None:
    anthropic, executor = normal_answer_script()
    body = await answer_text(make_deps(anthropic, executor), [user("Top 2?")], "m")
    t = parse_stream(body)
    assert t.completed
    assert [call.name for call in t.tool_calls] == ["run_sql", "show_table"]
    assert len(t.views) == 1


def test_lines_can_arrive_one_at_a_time_with_crlf_and_comments() -> None:
    builder = TranscriptBuilder()
    for line in [
        ": keep-alive",
        'data: {"type":"start","messageId":"m"}\r',
        "",
        'data: {"type":"start-step"}',
        'data: {"type":"text-start","id":"t1"}',
        'data: {"type":"text-delta","id":"t1","delta":"Hel"}',
        'data: {"type":"text-delta","id":"t1","delta":"lo"}',
        'data: {"type":"text-end","id":"t1"}',
        'data: {"type":"finish-step"}',
        'data: {"type":"finish","finishReason":"stop"}',
        "data: [DONE]",
    ]:
        builder.feed_line(line)
    t = builder.finish()
    assert t.text == "Hello"
    assert t.completed


def test_a_stream_cut_off_mid_text_keeps_what_arrived() -> None:
    t = parse_stream(
        'data: {"type":"start","messageId":"m"}\n\n'
        'data: {"type":"text-start","id":"t1"}\n\n'
        'data: {"type":"text-delta","id":"t1","delta":"Partial"}\n\n'
    )
    assert t.text == "Partial"
    assert not t.done
    assert not t.completed


def test_an_output_for_an_unseen_call_is_still_recorded() -> None:
    t = parse_stream('data: {"type":"tool-output-error","toolCallId":"x","errorText":"boom"}\n')
    assert t.tool_calls[0].error == "boom"


@pytest.mark.parametrize("line", ["event: message", "data: {not json", "data: [1, 2]"])
def test_malformed_lines_are_rejected(line: str) -> None:
    with pytest.raises(StreamParseError):
        TranscriptBuilder().feed_line(line)
