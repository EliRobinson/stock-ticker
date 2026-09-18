"""One step's model call: the spend reservation, the Anthropic stream, the one
retry, and settling the reservation with the usage the SDK reported.

Retries: the SDK's own `max_retries` is 0. A 429, 529, or 5xx is retried once,
honoring `retry-after`, and only if the step has not streamed anything yet.

Settling never under-counts:
- The API refused the request before streaming (an `APIStatusError` at
  stream open): $0, since nothing was billed.
- The call stopped before `message_start` any other way (connection error,
  timeout, cancellation): the request may have been processed, so it is
  charged its input bound at the input rate.
- The call stopped after `message_start` but before the final output count:
  reported usage plus the full output allowance.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam, ToolParam, ToolUseBlock

from stockticker.ai import errors
from stockticker.ai.pricing import ModelPrice, TokenUsage, cost_usd, worst_case_cost_usd
from stockticker.ai.spend import SpendGate, SpendGateError, SpendLedger
from stockticker.ai.stream import Emit, UIMessageStreamEncoder
from stockticker.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Spend:
    """What an answer's model calls reported and cost, across retries."""

    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: Decimal = Decimal(0)


@dataclass(frozen=True)
class CallSettings:
    model: str
    price: ModelPrice
    max_output_tokens: int
    max_retry_wait_seconds: float
    input_token_overhead: int
    ledger: SpendLedger
    spend_limit_usd: Decimal
    daily_token_budget: int
    day_start: Callable[[], datetime]
    sleep: Callable[[float], Awaitable[None]]


@dataclass
class CallResult:
    content: list[Any]
    stop_reason: str | None
    tool_uses: list[ToolUseBlock]


class ModelCall:
    def __init__(
        self,
        *,
        settings: CallSettings,
        client: AsyncAnthropic,
        encoder: UIMessageStreamEncoder,
        emit: Emit,
        spend: Spend,
        next_text_id: Callable[[], str],
        remaining_seconds: Callable[[], float],
        system: Sequence[TextBlockParam],
        tools: Sequence[ToolParam],
        messages: Sequence[MessageParam],
    ) -> None:
        self.settings = settings
        self.client = client
        self.encoder = encoder
        self.emit = emit
        self.spend = spend
        self.next_text_id = next_text_id
        self.remaining_seconds = remaining_seconds
        self.system = system
        self.tools = tools
        self.messages = messages
        self.step_started = False

    async def run(self) -> CallResult:
        """Streams the call's parts and returns what the model produced. The
        step's `start-step` is sent once, even across the retry."""
        for attempt in (1, 2):
            try:
                result = await self._attempt()
                await self._ensure_step()
                return result
            except anthropic.APIStatusError as error:
                wait = self._retry_wait(error)
                if attempt == 1 and not self.step_started and wait is not None:
                    logger.warning("ai_model_retry", status=error.status_code, wait_seconds=wait)
                    await self.settings.sleep(wait)
                    continue
                raise
        raise AssertionError("unreachable")

    def _retry_wait(self, error: anthropic.APIStatusError) -> float | None:
        if not errors.is_retryable(error):
            return None
        wait = errors.retry_after_seconds(error)
        if wait > self.settings.max_retry_wait_seconds or wait >= self.remaining_seconds() - 1:
            return None
        return wait

    async def _ensure_step(self) -> None:
        if not self.step_started:
            self.step_started = True
            await self.emit(self.encoder.start_step())

    async def _attempt(self) -> CallResult:
        settings = self.settings
        input_bound = input_token_bound(self.system, self.tools, self.messages, settings.input_token_overhead)
        worst_case = worst_case_cost_usd(
            settings.price, max_input_tokens=input_bound, max_output_tokens=settings.max_output_tokens
        )
        gate = SpendGate(
            limit_usd=settings.spend_limit_usd,
            daily_token_budget=settings.daily_token_budget,
            day_start=settings.day_start(),
        )
        try:
            reservation = await settings.ledger.reserve(
                model=settings.model, worst_case_usd=worst_case, gate=gate
            )
        except SpendGateError as error:
            raise errors.AnswerStopped(str(error)) from None

        meter = UsageMeter(input_bound=input_bound)
        try:
            return await self._stream(meter)
        except anthropic.APIStatusError:
            meter.refused_before_start = not meter.billed
            raise
        finally:
            usage, cost = meter.settle(settings.price, settings.max_output_tokens)
            self.spend.usage += usage
            self.spend.cost += cost
            await asyncio.shield(_settle(settings.ledger, reservation, usage, cost))

    async def _stream(self, meter: UsageMeter) -> CallResult:
        encoder = self.encoder
        open_text: dict[int, str] = {}
        async with self.client.messages.stream(
            model=self.settings.model,
            max_tokens=self.settings.max_output_tokens,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            # Automatic caching puts a breakpoint on the last block, so each
            # step reads the previous steps from cache; the explicit breakpoint
            # on the stable system block (prompt.py) lets a new answer reuse
            # the tools and system prompt.
            cache_control={"type": "ephemeral"},
        ) as stream:
            async for event in stream:
                if event.type == "message_start":
                    meter.started(event.message.usage)
                elif event.type == "message_delta":
                    meter.delta(event.usage)
                elif event.type == "content_block_start" and event.content_block.type == "text":
                    await self._ensure_step()
                    open_text[event.index] = self.next_text_id()
                    await self.emit(encoder.text_start(open_text[event.index]))
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    text_id = open_text.get(event.index)
                    if text_id is not None and event.delta.text:
                        await self.emit(encoder.text_delta(text_id, event.delta.text))
                elif event.type == "content_block_stop":
                    block = event.content_block
                    if block.type == "text" and event.index in open_text:
                        await self.emit(encoder.text_end(open_text.pop(event.index)))
                    elif block.type == "tool_use":
                        await self._ensure_step()
                        await self.emit(encoder.tool_input_available(block.id, block.name, block.input))
            final = await stream.get_final_message()
        return CallResult(
            content=list(final.content),
            stop_reason=final.stop_reason,
            tool_uses=[block for block in final.content if isinstance(block, ToolUseBlock)],
        )


class UsageMeter:
    """Usage as the SDK reports it while the stream runs. `message_start`
    carries the input counts; `message_delta` carries the final output count."""

    def __init__(self, *, input_bound: int) -> None:
        self.input_bound = input_bound
        self.billed = False
        self.completed = False
        self.refused_before_start = False
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
        """(reported usage, cost to record). See the module docstring."""
        if not self.billed:
            if self.refused_before_start:
                return self.usage, Decimal(0)
            return self.usage, cost_usd(price, TokenUsage(input_tokens=self.input_bound))
        cost = cost_usd(price, self.usage)
        if not self.completed:
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


def input_token_bound(system: Any, tools: Any, messages: Any, overhead: int) -> int:
    """An upper bound on the call's input tokens: every token is at least one
    byte, so the UTF-8 size of the JSON request body bounds the token count."""
    body = json.dumps({"system": system, "tools": tools, "messages": messages}, default=_jsonable)
    return len(body.encode()) + overhead


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)
