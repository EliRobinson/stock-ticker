"""The Ask tool loop (system design §6): one model call per step, tools run
between calls, every part streamed as the AI SDK UI message stream.

Budgets per answer: 8 steps, 60 s of wall time, 150k input tokens. The wall
clock covers the whole answer (loading the prompt context, every spend
reservation and settlement, opening each model stream, and every tool) as one
`asyncio.timeout`. The history sent to the model is trimmed, oldest question
first, so even the first call fits the input-token budget.

`run_answer` is a coroutine that sends each SSE event through `emit`, so the
timeout and any failure are caught inside it and turned into closing parts.
Cancellation (the browser disconnected) arrives as `CancelledError`: the
Anthropic stream closes by leaving its `async with`, a running query is
cancelled by asyncpg, and nothing more is emitted.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from functools import partial
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam, ToolParam, ToolUseBlock

from stockticker.ai import errors
from stockticker.ai.convert import UIMessage, to_anthropic_messages
from stockticker.ai.executor import SqlExecutor
from stockticker.ai.guard import AiSurface
from stockticker.ai.model_call import CallSettings, ModelCall, Spend, input_token_bound
from stockticker.ai.pricing import price_for
from stockticker.ai.serialize import tool_result_block
from stockticker.ai.spend import SpendLedger
from stockticker.ai.stream import (
    Emit,
    FinishReason,
    UIMessageStreamEncoder,
    never_disconnects,
    until_disconnected,
)
from stockticker.ai.tools import TOOL_NAMES, AnswerTools, ToolFailure, ToolOutcome, anthropic_tools
from stockticker.logging import get_logger

logger = get_logger(__name__)

TRUNCATED_TOOL_INPUT = (
    "The tool input was cut off at the output limit. Call the tool again with a shorter input."
)


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
    surface: AiSurface


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
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def stream_answer(deps: ChatDeps, ui_messages: list[UIMessage], message_id: str) -> AsyncIterator[str]:
    """The answer as SSE events, for a caller that reads to the end."""
    return until_disconnected(answer_producer(deps, ui_messages, message_id), never_disconnects)


def answer_producer(
    deps: ChatDeps, ui_messages: list[UIMessage], message_id: str
) -> Callable[[Emit], Awaitable[None]]:
    return partial(run_answer, deps, ui_messages, message_id)


async def run_answer(deps: ChatDeps, ui_messages: list[UIMessage], message_id: str, emit: Emit) -> None:
    encoder = UIMessageStreamEncoder(message_id)
    if deps.client is None:
        await _emit_all(emit, encoder.fail(errors.NO_KEY))
        return
    price = price_for(deps.model)
    if price is None:
        logger.error("ai_model_unpriced", model=deps.model, fix="add a price to stockticker/ai/pricing.py")
        await _emit_all(emit, encoder.fail(errors.model_unpriced(deps.model)))
        return
    settings = CallSettings(
        model=deps.model,
        price=price,
        max_output_tokens=deps.limits.max_output_tokens,
        max_retry_wait_seconds=deps.limits.max_retry_wait_seconds,
        input_token_overhead=deps.limits.input_token_overhead,
        ledger=deps.ledger,
        spend_limit_usd=deps.spend_limit_usd,
        daily_token_budget=deps.daily_token_budget,
        day_start=deps.day_start,
        sleep=deps.sleep,
    )
    answer = _Answer(deps, deps.client, settings, encoder, emit)
    await answer.run(to_anthropic_messages(ui_messages, tool_names=TOOL_NAMES))


class _Answer:
    def __init__(
        self,
        deps: ChatDeps,
        client: AsyncAnthropic,
        settings: CallSettings,
        encoder: UIMessageStreamEncoder,
        emit: Emit,
    ) -> None:
        self.deps = deps
        self.limits = deps.limits
        self.client = client
        self.settings = settings
        self.encoder = encoder
        self.emit = emit
        self.spend = Spend()
        self.steps = 0
        self.text_ids = 0
        self.outcome = "cancelled"
        loop = asyncio.get_running_loop()
        self.deadline = loop.time() + self.limits.wall_seconds

    async def run(self, messages: list[MessageParam]) -> None:
        try:
            await self.emit(self.encoder.start())
            try:
                async with asyncio.timeout_at(self.deadline):
                    await self._steps(messages)
            except TimeoutError:
                raise errors.AnswerStopped(errors.out_of_time(self.limits.wall_seconds)) from None
        except errors.AnswerStopped as stop:
            self.outcome = f"stopped: {stop}"
            await _emit_all(self.emit, self.encoder.fail(str(stop)))
        except Exception as error:
            logger.exception("ai_answer_failed")
            self.outcome = f"failed: {type(error).__name__}"
            await _emit_all(self.emit, self.encoder.fail(errors.describe(error)))
        finally:
            usage = self.spend.usage
            logger.info(
                "ai_answer",
                outcome=self.outcome,
                steps=self.steps,
                input_tokens=usage.input_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=str(self.spend.cost),
            )

    async def _steps(self, messages: list[MessageParam]) -> None:
        if not messages:
            raise errors.AnswerStopped(errors.NO_QUESTION)
        try:
            context = await self.deps.load_context()
        except Exception as error:
            logger.warning("ai_context_failed", error=str(error))
            raise errors.AnswerStopped(errors.DATABASE_UNREACHABLE) from None
        tool_params = anthropic_tools()
        fitted = self._fit_history(context.system, tool_params, messages)
        tools = AnswerTools(executor=self.deps.executor, surface=context.surface)

        for step in range(1, self.limits.max_steps + 1):
            self.steps = step
            if self.spend.usage.total_input_tokens >= self.limits.max_input_tokens:
                raise errors.AnswerStopped(errors.input_budget_used(self.limits.max_input_tokens))
            call = ModelCall(
                settings=self.settings,
                client=self.client,
                encoder=self.encoder,
                emit=self.emit,
                spend=self.spend,
                next_text_id=self._next_text_id,
                remaining_seconds=self._remaining_seconds,
                system=context.system,
                tools=tool_params,
                messages=fitted,
            )
            result = await call.run()
            if result.stop_reason == "refusal":
                raise errors.AnswerStopped(errors.REFUSED)
            if not result.tool_uses:
                await self.emit(self.encoder.finish_step())
                self.outcome = "answered"
                finish: FinishReason = "length" if result.stop_reason == "max_tokens" else "stop"
                await _emit_all(self.emit, self.encoder.finish(finish))
                return

            tools.step = step
            tool_results = [
                await self._run_tool(tools, block, result.stop_reason) for block in result.tool_uses
            ]
            fitted.append({"role": "assistant", "content": result.content})
            fitted.append({"role": "user", "content": tool_results})  # type: ignore[typeddict-item]
            await self.emit(self.encoder.finish_step())
        raise errors.AnswerStopped(errors.too_many_steps(self.limits.max_steps))

    def _fit_history(
        self, system: list[TextBlockParam], tools: list[ToolParam], messages: list[MessageParam]
    ) -> list[MessageParam]:
        """Drops the oldest questions (with their answers) until the first
        call's input bound fits the answer's input-token budget."""

        def fits(candidate: list[MessageParam]) -> bool:
            bound = input_token_bound(system, tools, candidate, self.limits.input_token_overhead)
            return bound <= self.limits.max_input_tokens

        if fits(messages):
            return list(messages)
        for start in _question_starts(messages):
            if fits(messages[start:]):
                logger.info("ai_history_trimmed", dropped_messages=start)
                return list(messages[start:])
        raise errors.AnswerStopped(errors.MESSAGE_TOO_LONG)

    async def _run_tool(
        self, tools: AnswerTools, block: ToolUseBlock, stop_reason: str | None
    ) -> dict[str, Any]:
        outcome: ToolOutcome
        if stop_reason == "max_tokens":
            outcome = ToolFailure(TRUNCATED_TOOL_INPUT)
        else:
            outcome = await tools.run(block.name, block.input)
        if isinstance(outcome, ToolFailure):
            await self.emit(self.encoder.tool_output_error(block.id, outcome.message))
        else:
            await self.emit(self.encoder.tool_output_available(block.id, outcome.output))
            if outcome.view is not None:
                await self.emit(self.encoder.data_view(outcome.view.id, outcome.view.model_dump(mode="json")))
        return tool_result_block(block.id, outcome.model_content, is_error=isinstance(outcome, ToolFailure))

    def _remaining_seconds(self) -> float:
        return self.deadline - asyncio.get_running_loop().time()

    def _next_text_id(self) -> str:
        self.text_ids += 1
        return f"{self.encoder.message_id}-text-{self.text_ids}"


def _question_starts(messages: list[MessageParam]) -> list[int]:
    """Indexes (after the first) where a turn is a plain user question, so
    history can be cut there without splitting a tool_use from its result."""
    starts = []
    for index, message in enumerate(messages):
        if index == 0 or message["role"] != "user":
            continue
        content = message["content"]
        if isinstance(content, str) or all(
            not (isinstance(block, dict) and block.get("type") == "tool_result") for block in content
        ):
            starts.append(index)
    return starts


async def _emit_all(emit: Emit, events: list[str]) -> None:
    for event in events:
        await emit(event)


def new_message_id() -> str:
    return f"msg-{uuid.uuid4().hex}"
