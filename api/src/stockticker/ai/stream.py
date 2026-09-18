"""Encoder for the AI SDK UI message stream protocol, v1 (system design §6).

Each part is one SSE event, `data: <json>\\n\\n`, and a finished stream ends
with `data: [DONE]\\n\\n`. The part shapes match `uiMessageChunkSchema` in the
`ai` package (packages/ai/src/ui-message-stream/ui-message-chunks.ts).

`UIMessageStreamEncoder` tracks which text parts and tool calls are still open,
so a failure can close every one of them before it sends `error` and `finish`.
After a client disconnect nothing is encoded at all; that is the caller's job
(it simply stops iterating).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from stockticker.logging import get_logger

_logger = get_logger(__name__)

UI_MESSAGE_STREAM_HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}
SSE_MEDIA_TYPE = "text/event-stream"
DONE = "data: [DONE]\n\n"

FinishReason = Literal["stop", "length", "content-filter", "tool-calls", "error", "other"]

UNFINISHED_TOOL_ERROR = "Not run. The answer stopped before this tool call finished."


def sse(part: dict[str, Any]) -> str:
    # Compact separators match JSON.stringify, which AI SDK Core uses.
    return f"data: {json.dumps(part, separators=(',', ':'), ensure_ascii=False)}\n\n"


class StreamStateError(RuntimeError):
    """A part was emitted out of protocol order. Always a bug in the caller."""


class UIMessageStreamEncoder:
    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self._started = False
        self._closed = False
        self._step_open = False
        self._open_text: list[str] = []
        self._open_tools: dict[str, str] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def open_tool_call_ids(self) -> list[str]:
        return list(self._open_tools)

    def start(self) -> str:
        self._require(not self._started, "start sent twice")
        self._started = True
        return sse({"type": "start", "messageId": self.message_id})

    def start_step(self) -> str:
        self._require_open()
        self._require(not self._step_open, "start-step inside an open step")
        self._step_open = True
        return sse({"type": "start-step"})

    def text_start(self, text_id: str) -> str:
        self._require_step()
        self._open_text.append(text_id)
        return sse({"type": "text-start", "id": text_id})

    def text_delta(self, text_id: str, delta: str) -> str:
        self._require(text_id in self._open_text, f"text-delta for unopened text {text_id}")
        return sse({"type": "text-delta", "id": text_id, "delta": delta})

    def text_end(self, text_id: str) -> str:
        self._require(text_id in self._open_text, f"text-end for unopened text {text_id}")
        self._open_text.remove(text_id)
        return sse({"type": "text-end", "id": text_id})

    def tool_input_available(self, tool_call_id: str, tool_name: str, tool_input: Any) -> str:
        self._require_step()
        self._open_tools[tool_call_id] = tool_name
        return sse(
            {
                "type": "tool-input-available",
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "input": tool_input,
            }
        )

    def tool_output_available(self, tool_call_id: str, output: Any) -> str:
        self._require(tool_call_id in self._open_tools, f"output for unknown tool call {tool_call_id}")
        del self._open_tools[tool_call_id]
        return sse({"type": "tool-output-available", "toolCallId": tool_call_id, "output": output})

    def tool_output_error(self, tool_call_id: str, error_text: str) -> str:
        self._require(tool_call_id in self._open_tools, f"error for unknown tool call {tool_call_id}")
        del self._open_tools[tool_call_id]
        return sse({"type": "tool-output-error", "toolCallId": tool_call_id, "errorText": error_text})

    def data_view(self, view_id: str, spec: dict[str, Any]) -> str:
        self._require_step()
        return sse({"type": "data-view", "id": view_id, "data": spec})

    def finish_step(self) -> str:
        self._require_step()
        self._require(not self._open_text, "finish-step with open text parts")
        self._require(not self._open_tools, "finish-step with unfinished tool calls")
        self._step_open = False
        return sse({"type": "finish-step"})

    def finish(self, finish_reason: FinishReason = "stop") -> list[str]:
        """Normal completion: `finish`, then the `[DONE]` terminator."""
        self._require_open()
        self._require(not self._step_open, "finish inside an open step")
        self._closed = True
        return [sse({"type": "finish", "finishReason": finish_reason}), DONE]

    def fail(self, error_text: str) -> list[str]:
        """Model error or budget exhausted: close every open part, then
        `error`, `finish`, and `[DONE]`. `finish-step` is not sent; the step
        did not finish."""
        if not self._started:
            events = [self.start()]
        else:
            self._require_open()
            events = []
        events.extend(self.text_end(text_id) for text_id in list(self._open_text))
        events.extend(
            self.tool_output_error(tool_call_id, UNFINISHED_TOOL_ERROR)
            for tool_call_id in list(self._open_tools)
        )
        self._step_open = False
        self._closed = True
        events.append(sse({"type": "error", "errorText": error_text}))
        events.append(sse({"type": "finish", "finishReason": "error"}))
        events.append(DONE)
        return events

    def _require_open(self) -> None:
        self._require(self._started, "part sent before start")
        self._require(not self._closed, "part sent after finish")

    def _require_step(self) -> None:
        self._require_open()
        self._require(self._step_open, "part sent outside a step")

    @staticmethod
    def _require(condition: bool, message: str) -> None:
        if not condition:
            raise StreamStateError(message)


_END = object()
_background_tasks: set[asyncio.Task[None]] = set()

Emit = Callable[[str], Awaitable[None]]
Producer = Callable[[Emit], Awaitable[None]]

# What the relay sends when the producer itself crashes. The producer closes its
# own parts on every failure it can see; this is the last resort, so the
# client still gets an error and a finished stream.
_CRASH_EVENTS = [
    sse({"type": "error", "errorText": "The answer stopped on an internal error. Try again."}),
    sse({"type": "finish", "finishReason": "error"}),
    DONE,
]


async def until_disconnected(
    producer: Producer,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    poll_seconds: float = 0.25,
) -> AsyncIterator[str]:
    """Runs `producer` in its own task and relays what it emits until the
    client disconnects.

    Because the producer runs apart from the response, a disconnect is noticed
    while the loop waits on the model or on Postgres, not only between chunks.
    On disconnect the task is cancelled (which closes the Anthropic stream and
    cancels the running query) and nothing more is yielded."""
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=64)
    finished = False

    async def emit(event: str) -> None:
        nonlocal finished
        finished = event == DONE
        await queue.put(event)

    async def run() -> None:
        try:
            await producer(emit)
        except Exception:
            _logger.exception("ai_stream_producer_failed")
            if not finished:
                for event in _CRASH_EVENTS:
                    await queue.put(event)
        await queue.put(_END)

    task = asyncio.create_task(run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    try:
        while True:
            getter = asyncio.ensure_future(queue.get())
            try:
                while not getter.done():
                    await asyncio.wait({getter}, timeout=poll_seconds)
                    if not getter.done() and await is_disconnected():
                        return
            finally:
                getter.cancel()
            item = getter.result()
            if item is _END:
                return
            if await is_disconnected():
                return
            assert isinstance(item, str)
            yield item
    finally:
        task.cancel()
