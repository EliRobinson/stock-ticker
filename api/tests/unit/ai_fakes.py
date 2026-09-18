"""Test doubles for the Ask loop, all at external boundaries.

- `ScriptedAnthropic`: a real `AsyncAnthropic` client whose HTTP transport
  replays scripted Messages API responses (SSE streams or error statuses), so
  the SDK's own parsing, error mapping, and streaming helpers run for real.
- `FakeExecutor`: stands in for Postgres behind `SqlExecutor`.
- `MemoryLedger`: an in-memory `SpendLedger` with the same gate rules.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx2
from anthropic import AsyncAnthropic

from stockticker.ai.convert import UIMessage
from stockticker.ai.executor import Column, QueryResult, ToolError
from stockticker.ai.loop import ChatDeps, Limits, PromptContext
from stockticker.ai.pricing import TokenUsage
from stockticker.ai.spend import LedgerTotals, SpendGate, check_gate

MODEL = "claude-sonnet-5"


# --- Anthropic SSE -------------------------------------------------------


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def message_start(input_tokens: int = 100, cache_read: int = 0, cache_write: int = 0) -> str:
    return _event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": 1,
                    "cache_creation_input_tokens": cache_write,
                    "cache_read_input_tokens": cache_read,
                },
            },
        },
    )


def text_block(index: int, *chunks: str) -> str:
    events = [
        _event(
            "content_block_start",
            {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
        )
    ]
    for chunk in chunks:
        events.append(
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": chunk},
                },
            )
        )
    events.append(_event("content_block_stop", {"type": "content_block_stop", "index": index}))
    return "".join(events)


def text_block_open(index: int, *chunks: str) -> str:
    """A text block that starts and streams but never stops (for mid-text failures)."""
    full = text_block(index, *chunks)
    return full[: full.rindex("event: content_block_stop")]


def tool_block(index: int, tool_id: str, name: str, tool_input: dict[str, Any]) -> str:
    return "".join(
        [
            _event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
                },
            ),
            _event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_input)},
                },
            ),
            _event("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
    )


def message_end(stop_reason: str, output_tokens: int = 50) -> str:
    return _event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    ) + _event("message_stop", {"type": "message_stop"})


def stream_error(error_type: str = "overloaded_error", message: str = "Overloaded") -> str:
    return _event("error", {"type": "error", "error": {"type": error_type, "message": message}})


def text_answer(*chunks: str, input_tokens: int = 100, output_tokens: int = 20) -> str:
    return message_start(input_tokens) + text_block(0, *chunks) + message_end("end_turn", output_tokens)


def tool_call(
    tool_id: str, name: str, tool_input: dict[str, Any], *, lead: str | None = None, input_tokens: int = 100
) -> str:
    body = message_start(input_tokens)
    index = 0
    if lead is not None:
        body += text_block(0, lead)
        index = 1
    return body + tool_block(index, tool_id, name, tool_input) + message_end("tool_use")


@dataclass
class HttpError:
    status: int
    error_type: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ConnectionDrop:
    """The connection fails before any response (no status, no message_start)."""


Scripted = str | HttpError | ConnectionDrop


class ScriptedAnthropic:
    """Replays one scripted response per `POST /v1/messages`."""

    def __init__(self, *responses: Scripted, stall_after_first_chunk: bool = False) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.stall_after_first_chunk = stall_after_first_chunk
        self.stream_closed = asyncio.Event()
        self.client = AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle)),
        )

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        if not self.responses:
            raise AssertionError("the loop made more model calls than the test scripted")
        response = self.responses.pop(0)
        if isinstance(response, ConnectionDrop):
            raise httpx2.ConnectError("connection dropped", request=request)
        if isinstance(response, HttpError):
            body = {"type": "error", "error": {"type": response.error_type, "message": response.error_type}}
            return httpx2.Response(response.status, json=body, headers=response.headers)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_SseStream(response, self),
        )


class _SseStream(httpx2.AsyncByteStream):
    def __init__(self, body: str, owner: ScriptedAnthropic) -> None:
        self.body = body
        self.owner = owner

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        events = self.body.split("\n\n")
        for i, event in enumerate(events):
            if event:
                yield (event + "\n\n").encode()
            if self.owner.stall_after_first_chunk and i >= 1:
                await asyncio.sleep(3600)

    async def aclose(self) -> None:
        self.owner.stream_closed.set()


# --- Postgres ------------------------------------------------------------


class FakeExecutor:
    def __init__(self, *results: QueryResult | ToolError, delay: float = 0.0) -> None:
        self.results = list(results)
        self.queries: list[str] = []
        self.delay = delay
        self.cancelled = asyncio.Event()

    async def execute(self, sql: str) -> QueryResult:
        self.queries.append(sql)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        result = self.results.pop(0)
        if isinstance(result, ToolError):
            raise result
        return result


def result(columns: list[tuple[str, str]], rows: list[tuple[Any, ...]]) -> QueryResult:
    return QueryResult(columns=[Column(name, type_) for name, type_ in columns], rows=rows)


# --- Spend ----------------------------------------------------------------


@dataclass
class LedgerRow:
    model: str
    state: str
    cost_usd: Decimal
    usage: TokenUsage = field(default_factory=TokenUsage)


class MemoryLedger:
    def __init__(self, spent: Decimal = Decimal(0), tokens_today: int = 0) -> None:
        self.rows: list[LedgerRow] = []
        self.initial_spent = spent
        self.tokens_today = tokens_today
        self.gates: list[tuple[Decimal, SpendGate]] = []

    async def reserve(self, *, model: str, worst_case_usd: Decimal, gate: SpendGate) -> int:
        self.gates.append((worst_case_usd, gate))
        tokens = self.tokens_today + sum(row.usage.total_tokens for row in self.rows)
        check_gate(LedgerTotals(await self.spent_usd(), tokens), worst_case_usd, gate)
        self.rows.append(LedgerRow(model=model, state="reserved", cost_usd=worst_case_usd))
        return len(self.rows) - 1

    async def settle(self, reservation_id: int, *, usage: TokenUsage, cost_usd: Decimal) -> None:
        row = self.rows[reservation_id]
        row.state, row.usage, row.cost_usd = "recorded", usage, cost_usd

    async def spent_usd(self) -> Decimal:
        return self.initial_spent + sum((row.cost_usd for row in self.rows), Decimal(0))


# --- wiring ---------------------------------------------------------------


class FakeClock:
    """Records retry waits instead of sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def prompt_context() -> PromptContext:
    return PromptContext(
        system=[
            {"type": "text", "text": "stable prompt", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Today is Thursday, 2026-09-17."},
        ],
        ai_views=frozenset({"companies", "market_caps", "daily_prices", "listings"}),
    )


def make_deps(
    anthropic: ScriptedAnthropic | None,
    executor: FakeExecutor | None = None,
    *,
    ledger: MemoryLedger | None = None,
    limits: Limits | None = None,
    clock: FakeClock | None = None,
    model: str = MODEL,
    spend_limit_usd: Decimal = Decimal("5.00"),
    daily_token_budget: int = 2_000_000,
    load_context: Callable[[], Awaitable[PromptContext]] | None = None,
) -> ChatDeps:
    clock = clock or FakeClock()

    async def default_context() -> PromptContext:
        return prompt_context()

    return ChatDeps(
        model=model,
        client=anthropic.client if anthropic is not None else None,
        executor=executor or FakeExecutor(),
        ledger=ledger or MemoryLedger(),
        load_context=load_context or default_context,
        spend_limit_usd=spend_limit_usd,
        daily_token_budget=daily_token_budget,
        day_start=lambda: datetime(2026, 9, 17, 4, tzinfo=UTC),
        limits=limits or Limits(),
        sleep=clock.sleep,
    )


def user(text: str, message_id: str = "u1") -> UIMessage:
    return UIMessage(id=message_id, role="user", parts=[{"type": "text", "text": text}])


def parse_sse(body: str) -> list[dict[str, Any] | str]:
    """SSE text -> parts, with the terminator as the string "[DONE]"."""
    parts: list[dict[str, Any] | str] = []
    for event in body.split("\n\n"):
        if not event:
            continue
        assert event.startswith("data: "), event
        payload = event.removeprefix("data: ")
        parts.append(payload if payload == "[DONE]" else json.loads(payload))
    return parts


def part_types(body: str) -> list[str]:
    return [p if isinstance(p, str) else str(p["type"]) for p in parse_sse(body)]


def error_texts(body: str) -> list[str]:
    return [str(p["errorText"]) for p in parse_sse(body) if isinstance(p, dict) and p["type"] == "error"]


async def answer_text(deps: ChatDeps, messages: list[UIMessage] | None = None, message_id: str = "m") -> str:
    """The whole SSE body of one answer."""
    from stockticker.ai.loop import stream_answer

    return "".join([c async for c in stream_answer(deps, messages or [user("q")], message_id)])


def unwrap_untrusted(content: str) -> Any:
    assert content.startswith("<untrusted_data>") and content.endswith("</untrusted_data>"), content
    return json.loads(content.removeprefix("<untrusted_data>").removesuffix("</untrusted_data>"))


# --- the scripted "normal answer": run_sql, show_table, then text --------------

QUESTION = "Which 2 companies are largest?"
TOP_SQL = (
    "SELECT c.name, m.market_cap FROM ai.market_caps m JOIN ai.companies c ON c.cik = m.cik "
    "ORDER BY m.market_cap DESC LIMIT 2"
)


def normal_answer_script(*extra: Scripted) -> tuple[ScriptedAnthropic, FakeExecutor]:
    """The script behind the `normal_answer_with_table` golden stream, plus
    any extra model responses for later turns."""
    anthropic = ScriptedAnthropic(
        tool_call(
            "toolu_01", "run_sql", {"sql": TOP_SQL, "purpose": "Rank by market cap"}, lead="Let me check."
        ),
        tool_call(
            "toolu_02",
            "show_table",
            {
                "result_id": "r1",
                "title": "Largest companies",
                "columns": [
                    {"key": "name", "label": "Company"},
                    {"key": "market_cap", "label": "Market cap", "format": "compact_currency"},
                ],
            },
        ),
        text_answer("Apple is the largest", " at $3.12T."),
        *extra,
    )
    executor = FakeExecutor(
        result([("name", "text"), ("market_cap", "numeric")], [("Apple Inc.", Decimal("3123456789012.00"))])
    )
    return anthropic, executor
