"""The Ask tool loop (system design §6): one model call per step, tools run
between calls, every part streamed as the AI SDK UI message stream.

Budgets per answer: 8 steps, 60 s of wall time, 150k input tokens. Before
every model call the spend gate (`stockticker.ai.spend`) reserves the call's
worst-case cost against `AI_SPEND_LIMIT_USD` and checks
`AI_DAILY_TOKEN_BUDGET`; after it, the reservation is settled with the usage
the SDK reported, even when the call failed partway or was cancelled.

Retries: the SDK's own `max_retries` is 0. A 429, 529, or 5xx is retried once,
honoring `retry-after`, and only if the step has not streamed anything yet.

Cancellation (the browser disconnected) arrives as `CancelledError` at
whatever is being awaited: the Anthropic stream is closed by leaving its
`async with`, and a running query is cancelled by asyncpg. Nothing more is
emitted; the caller stops reading.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam, ToolUseBlock

from stockticker.ai.convert import UIMessage, to_anthropic_messages
from stockticker.ai.executor import SqlExecutor
from stockticker.ai.pricing import ModelPrice, TokenUsage, cost_usd, price_for, worst_case_cost_usd
from stockticker.ai.spend import SpendGate, SpendGateError, SpendLedger
from stockticker.ai.stream import FinishReason, UIMessageStreamEncoder
from stockticker.ai.tools import AnswerTools, anthropic_tools
from stockticker.logging import get_logger

logger = get_logger(__name__)

NO_KEY_ERROR = "AI is off. ANTHROPIC_API_KEY is not set."
_T = TypeVar("_T")


@dataclass(frozen=True)
class Limits:
    max_steps: int = 8
    wall_seconds: float = 60.0
    max_input_tokens: int = 150_000
    max_output_tokens: int = 8_192
    max_retry_wait_seconds: float = 10.0
    input_token_overhead: int = 2_048
    """Added to the byte count when bounding a call's input tokens (message
    and tool framing the API adds)."""


@dataclass(frozen=True)
class PromptContext:
    system: list[TextBlockParam]
    ai_views: frozenset[str]


@dataclass
class ChatDeps:
    model: str
    client: AsyncAnthropic | None
    executor: SqlExecutor
    ledger: SpendLedger
    load_context: Callable[[], Awaitable[PromptContext]]
    spend_limit_usd: Decimal
    daily_token_budget: int
    day_start: Callable[[], datetime]
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class _StopAnswer(Exception):
    """Ends the answer with an `error` part. `str()` is the user-facing text."""


@dataclass
class _CallResult:
    content: list[Any]
    stop_reason: str | None
    tool_uses: list[ToolUseBlock]


async def stream_answer(deps: ChatDeps, ui_messages: list[UIMessage], message_id: str) -> AsyncIterator[str]:
    encoder = UIMessageStreamEncoder(message_id)
    if deps.client is None:
        for event in encoder.fail(NO_KEY_ERROR):
            yield event
        return
    price = price_for(deps.model)
    if price is None:
        for event in encoder.fail(
            f"AI is off. No price is set for model {deps.model}. Add it to stockticker/ai/pricing.py."
        ):
            yield event
        return
    run = _AnswerRun(deps, deps.client, price, encoder)
    async for event in run.stream(to_anthropic_messages(ui_messages)):
        yield event


class _AnswerRun:
    def __init__(
        self, deps: ChatDeps, client: AsyncAnthropic, price: ModelPrice, encoder: UIMessageStreamEncoder
    ) -> None:
        self.deps = deps
        self.client = client
        self.price = price
        self.encoder = encoder
        self.limits = deps.limits
        self.deadline = deps.clock() + self.limits.wall_seconds
        self.usage = TokenUsage()
        self.cost = Decimal(0)
        self.steps = 0
        self.text_ids = 0
        self.outcome = "cancelled"

    async def stream(self, messages: list[MessageParam]) -> AsyncIterator[str]:
        try:
            yield self.encoder.start()
            if not messages:
                raise _StopAnswer("There is no question to answer. Send a message.")
            try:
                context = await self.deps.load_context()
            except Exception as error:
                logger.warning("ai_context_failed", error=str(error))
                raise _StopAnswer("The database is not reachable. Try again.") from None
            tools = AnswerTools(executor=self.deps.executor, ai_views=context.ai_views)
            async for event in self._steps(context, tools, list(messages)):
                yield event
        except _StopAnswer as stop:
            self.outcome = f"stopped: {stop}"
            for event in self.encoder.fail(str(stop)):
                yield event
        except Exception as error:
            logger.exception("ai_answer_failed")
            self.outcome = f"failed: {type(error).__name__}"
            for event in self.encoder.fail(_describe_error(error)):
                yield event
        finally:
            logger.info(
                "ai_answer",
                outcome=self.outcome,
                steps=self.steps,
                input_tokens=self.usage.input_tokens,
                cache_creation_input_tokens=self.usage.cache_creation_input_tokens,
                cache_read_input_tokens=self.usage.cache_read_input_tokens,
                output_tokens=self.usage.output_tokens,
                cost_usd=str(self.cost),
            )

    async def _steps(
        self, context: PromptContext, tools: AnswerTools, messages: list[MessageParam]
    ) -> AsyncIterator[str]:
        tool_params = anthropic_tools()
        for step in range(1, self.limits.max_steps + 1):
            self.steps = step
            if self.usage.total_input_tokens >= self.limits.max_input_tokens:
                raise _StopAnswer(
                    f"Stopped at this answer's {self.limits.max_input_tokens:,} input-token limit. "
                    "Ask a narrower question."
                )
            call = _ModelCall(self, context.system, tool_params, messages)
            async for event in call.stream():
                yield event
            result = call.result
            assert result is not None

            if result.stop_reason == "refusal":
                raise _StopAnswer("The model declined to answer. Rephrase the question.")
            if not result.tool_uses:
                yield self.encoder.finish_step()
                self.outcome = "answered"
                finish: FinishReason = "length" if result.stop_reason == "max_tokens" else "stop"
                for event in self.encoder.finish(finish):
                    yield event
                return

            tools.step = step
            tool_results: list[dict[str, Any]] = []
            for block in result.tool_uses:
                async for event in self._run_tool(tools, block, result.stop_reason, tool_results):
                    yield event
            messages.append({"role": "assistant", "content": result.content})
            messages.append({"role": "user", "content": tool_results})  # type: ignore[typeddict-item]
            yield self.encoder.finish_step()
        raise _StopAnswer(
            f"Stopped after {self.limits.max_steps} steps without a final answer. Ask a narrower question."
        )

    async def _run_tool(
        self, tools: AnswerTools, block: ToolUseBlock, stop_reason: str | None, results: list[dict[str, Any]]
    ) -> AsyncIterator[str]:
        if stop_reason == "max_tokens":
            error = (
                "The tool input was cut off at the output limit. Call the tool again with a shorter input."
            )
            yield self.encoder.tool_output_error(block.id, error)
            results.append(_tool_result(block.id, json.dumps({"error": error}), is_error=True))
            return
        outcome = await self.within_deadline(tools.run(block.name, block.input))
        if outcome.error is not None:
            yield self.encoder.tool_output_error(block.id, outcome.error)
        else:
            yield self.encoder.tool_output_available(block.id, outcome.output)
            if outcome.view is not None and outcome.view_id is not None:
                yield self.encoder.data_view(outcome.view_id, outcome.view)
        results.append(_tool_result(block.id, outcome.model_content, is_error=outcome.is_error))

    def remaining_seconds(self) -> float:
        return self.deadline - self.deps.clock()

    async def within_deadline(self, awaitable: Awaitable[_T]) -> _T:
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise _StopAnswer(self._deadline_message())
        try:
            return await asyncio.wait_for(awaitable, timeout=remaining)
        except TimeoutError:
            raise _StopAnswer(self._deadline_message()) from None

    def _deadline_message(self) -> str:
        return (
            f"Stopped after {self.limits.wall_seconds:g} s without a final answer. Ask a narrower question."
        )

    def next_text_id(self) -> str:
        self.text_ids += 1
        return f"{self.encoder.message_id}-text-{self.text_ids}"


class _ModelCall:
    """One step's model call: the spend reservation, the stream, the retry,
    and settling the reservation with the reported usage."""

    def __init__(
        self, run: _AnswerRun, system: list[TextBlockParam], tools: list[Any], messages: list[MessageParam]
    ) -> None:
        self.run = run
        self.system = system
        self.tools = tools
        self.messages = messages
        self.step_started = False
        self.result: _CallResult | None = None

    def _ensure_step(self) -> Iterable[str]:
        if not self.step_started:
            self.step_started = True
            yield self.run.encoder.start_step()

    async def stream(self) -> AsyncIterator[str]:
        for attempt in (1, 2):
            try:
                async for event in self._attempt():
                    yield event
                if not self.step_started:
                    yield self.run.encoder.start_step()
                    self.step_started = True
                return
            except anthropic.APIStatusError as error:
                wait = self._retry_wait(error)
                if attempt == 1 and not self.step_started and wait is not None:
                    logger.warning("ai_model_retry", status=error.status_code, wait_seconds=wait)
                    await self.run.deps.sleep(wait)
                    continue
                raise

    def _retry_wait(self, error: anthropic.APIStatusError) -> float | None:
        if not _is_retryable(error):
            return None
        wait = _retry_after_seconds(error)
        if wait > self.run.limits.max_retry_wait_seconds or wait >= self.run.remaining_seconds() - 1:
            return None
        return wait

    async def _attempt(self) -> AsyncIterator[str]:
        run = self.run
        deps = run.deps
        max_input = _input_token_bound(
            self.system, self.tools, self.messages, run.limits.input_token_overhead
        )
        worst_case = worst_case_cost_usd(
            run.price, max_input_tokens=max_input, max_output_tokens=run.limits.max_output_tokens
        )
        gate = SpendGate(
            limit_usd=deps.spend_limit_usd,
            daily_token_budget=deps.daily_token_budget,
            day_start=deps.day_start(),
        )
        try:
            reservation = await deps.ledger.reserve(model=deps.model, worst_case_usd=worst_case, gate=gate)
        except SpendGateError as error:
            raise _StopAnswer(str(error)) from None

        meter = _UsageMeter()
        try:
            async for event in self._stream_events(meter):
                yield event
        finally:
            usage, cost = meter.settle(run.price, run.limits.max_output_tokens)
            run.usage += usage
            run.cost += cost
            await asyncio.shield(_settle(deps.ledger, reservation, usage, cost))

    async def _stream_events(self, meter: _UsageMeter) -> AsyncIterator[str]:
        run = self.run
        encoder = run.encoder
        open_text: dict[int, str] = {}
        async with run.client.messages.stream(
            model=run.deps.model,
            max_tokens=run.limits.max_output_tokens,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            cache_control={"type": "ephemeral"},
        ) as stream:
            iterator = stream.__aiter__()
            while True:
                try:
                    event = await run.within_deadline(iterator.__anext__())
                except StopAsyncIteration:
                    break
                if event.type == "message_start":
                    meter.started(event.message.usage)
                elif event.type == "message_delta":
                    meter.delta(event.usage)
                elif event.type == "content_block_start" and event.content_block.type == "text":
                    for part in self._ensure_step():
                        yield part
                    open_text[event.index] = run.next_text_id()
                    yield encoder.text_start(open_text[event.index])
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    text_id = open_text.get(event.index)
                    if text_id is not None and event.delta.text:
                        yield encoder.text_delta(text_id, event.delta.text)
                elif event.type == "content_block_stop":
                    block = event.content_block
                    if block.type == "text" and event.index in open_text:
                        yield encoder.text_end(open_text.pop(event.index))
                    elif block.type == "tool_use":
                        for part in self._ensure_step():
                            yield part
                        yield encoder.tool_input_available(block.id, block.name, block.input)
            final = await stream.get_final_message()
        self.result = _CallResult(
            content=list(final.content),
            stop_reason=final.stop_reason,
            tool_uses=[block for block in final.content if isinstance(block, ToolUseBlock)],
        )


class _UsageMeter:
    """Usage as the SDK reports it while the stream runs. `message_start`
    carries the input counts; `message_delta` carries the final output count."""

    def __init__(self) -> None:
        self.billed = False
        self.completed = False
        self.usage = TokenUsage()

    def started(self, usage: Any) -> None:
        self.billed = True
        self.usage = TokenUsage(
            input_tokens=usage.input_tokens or 0,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
        )

    def delta(self, usage: Any) -> None:
        self.completed = True
        self.usage = TokenUsage(
            input_tokens=_or(usage.input_tokens, self.usage.input_tokens),
            cache_creation_input_tokens=_or(
                usage.cache_creation_input_tokens, self.usage.cache_creation_input_tokens
            ),
            cache_read_input_tokens=_or(usage.cache_read_input_tokens, self.usage.cache_read_input_tokens),
            output_tokens=_or(usage.output_tokens, self.usage.output_tokens),
        )

    def settle(self, price: ModelPrice, max_output_tokens: int) -> tuple[TokenUsage, Decimal]:
        cost = cost_usd(price, self.usage)
        if self.billed and not self.completed:
            # The call stopped before the final output count arrived (error or
            # disconnect). Charge the full output allowance so the ledger never
            # under-counts; the reported tokens stay as reported.
            unreported = max(0, max_output_tokens - self.usage.output_tokens)
            cost += cost_usd(price, TokenUsage(output_tokens=unreported))
        return self.usage, cost


def _or(value: int | None, fallback: int) -> int:
    return fallback if value is None else value


async def _settle(ledger: SpendLedger, reservation: int, usage: TokenUsage, cost: Decimal) -> None:
    try:
        await ledger.settle(reservation, usage=usage, cost_usd=cost)
    except Exception:
        # The reservation keeps its worst-case cost, so spend is over-counted, never under.
        logger.exception("ai_spend_settle_failed", reservation=reservation)


def _tool_result(tool_use_id: str, content: str, *, is_error: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        result["is_error"] = True
    return result


def _input_token_bound(system: Any, tools: Any, messages: Any, overhead: int) -> int:
    """An upper bound on the call's input tokens: every token is at least one
    byte, so the UTF-8 size of the JSON request body bounds the token count."""
    body = json.dumps({"system": system, "tools": tools, "messages": messages}, default=_jsonable)
    return len(body.encode()) + overhead


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


_RETRYABLE_ERROR_TYPES = frozenset({"rate_limit_error", "overloaded_error", "api_error"})


def _is_retryable(error: anthropic.APIStatusError) -> bool:
    status = error.status_code
    if status in (429, 529) or status >= 500:
        return True
    body = error.body
    if isinstance(body, dict):
        inner = body.get("error")
        if isinstance(inner, dict) and inner.get("type") in _RETRYABLE_ERROR_TYPES:
            return True
    return False


def _retry_after_seconds(error: anthropic.APIStatusError) -> float:
    value = error.response.headers.get("retry-after") if error.response is not None else None
    try:
        return max(0.0, float(value)) if value is not None else 1.0
    except ValueError:
        return 1.0


def _describe_error(error: Exception) -> str:
    if isinstance(error, anthropic.AuthenticationError):
        return "Anthropic rejected ANTHROPIC_API_KEY. Set a valid key."
    if isinstance(error, anthropic.PermissionDeniedError):
        return "Anthropic refused the request (403). Check the key's permissions."
    if isinstance(error, anthropic.RateLimitError):
        return "Anthropic rate limit reached. Try again."
    if isinstance(error, anthropic.APIStatusError):
        if _is_retryable(error):
            return f"Anthropic returned an error ({_error_type(error)}), so the answer stopped. Try again."
        return (
            f"Anthropic rejected the request ({_error_type(error)}), so the answer stopped. Start a new chat."
        )
    if isinstance(error, anthropic.APIConnectionError):
        return "Anthropic could not be reached. Try again."
    return "The answer stopped on an internal error. Try again."


def _error_type(error: anthropic.APIStatusError) -> str:
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("type") or error.status_code)
    return str(error.status_code)


def new_message_id() -> str:
    return f"msg-{uuid.uuid4().hex}"
