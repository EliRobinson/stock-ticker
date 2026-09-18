"""One Ask answer, read back from its AI SDK UI message stream (system design §6).

`TranscriptBuilder` takes the stream one SSE line at a time, so the runner can
feed it straight from the HTTP response. It keeps what the graders need: the
answer text, every tool call with its input and outcome, every `data-view`
spec, how many steps ran, and how the stream ended.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    call_id: str
    name: str
    input: dict[str, Any]
    output: Any = None
    error: str | None = None

    @property
    def sql(self) -> str | None:
        value = self.input.get("sql") if self.name == "run_sql" else None
        return value if isinstance(value, str) else None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.output is not None


@dataclass
class Transcript:
    texts: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    views: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    error: str | None = None
    finish_reason: str | None = None
    done: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(part for part in self.texts if part.strip())

    @property
    def sql_calls(self) -> list[ToolCall]:
        return [call for call in self.tool_calls if call.name == "run_sql"]

    @property
    def completed(self) -> bool:
        """The stream ended normally: `finish` without an `error` part, then `[DONE]`."""
        return self.done and self.error is None and self.finish_reason not in (None, "error")


class StreamParseError(ValueError):
    """The body is not an AI SDK UI message stream."""


class TranscriptBuilder:
    def __init__(self) -> None:
        self.transcript = Transcript()
        self._open_text: dict[str, list[str]] = {}
        self._calls: dict[str, ToolCall] = {}

    def feed_line(self, line: str) -> None:
        line = line.rstrip("\r")
        if not line or line.startswith(":"):
            return
        if not line.startswith("data:"):
            raise StreamParseError(f"not an SSE data line: {line[:80]!r}")
        payload = line.removeprefix("data:").strip()
        if payload == "[DONE]":
            self.transcript.done = True
            return
        try:
            part = json.loads(payload)
        except json.JSONDecodeError as error:
            raise StreamParseError(f"bad JSON in stream part: {payload[:80]!r}") from error
        if not isinstance(part, dict):
            raise StreamParseError(f"stream part is not an object: {payload[:80]!r}")
        self._apply(part)

    def feed(self, body: str) -> Transcript:
        for line in body.splitlines():
            self.feed_line(line)
        return self.finish()

    def finish(self) -> Transcript:
        # A stream cut off mid-text still keeps the text it sent.
        for text_id in list(self._open_text):
            self.transcript.texts.append("".join(self._open_text.pop(text_id)))
        return self.transcript

    def _apply(self, part: dict[str, Any]) -> None:
        kind = part.get("type")
        t = self.transcript
        if kind == "start-step":
            t.steps += 1
        elif kind == "text-start":
            self._open_text[str(part["id"])] = []
        elif kind == "text-delta":
            self._open_text.setdefault(str(part["id"]), []).append(str(part.get("delta", "")))
        elif kind == "text-end":
            t.texts.append("".join(self._open_text.pop(str(part["id"]), [])))
        elif kind == "tool-input-available":
            raw_input = part.get("input")
            call = ToolCall(
                call_id=str(part["toolCallId"]),
                name=str(part.get("toolName", "")),
                input=raw_input if isinstance(raw_input, dict) else {"raw": raw_input},
            )
            self._calls[call.call_id] = call
            t.tool_calls.append(call)
        elif kind == "tool-output-available":
            self._call(part).output = part.get("output")
        elif kind == "tool-output-error":
            self._call(part).error = str(part.get("errorText", ""))
        elif kind == "data-view":
            data = part.get("data")
            if isinstance(data, dict):
                t.views.append(data)
        elif kind == "error":
            t.error = str(part.get("errorText", ""))
        elif kind == "finish":
            t.finish_reason = str(part.get("finishReason", "stop"))

    def _call(self, part: dict[str, Any]) -> ToolCall:
        call_id = str(part["toolCallId"])
        call = self._calls.get(call_id)
        if call is None:
            call = ToolCall(call_id=call_id, name="", input={})
            self._calls[call_id] = call
            self.transcript.tool_calls.append(call)
        return call


def parse_stream(body: str) -> Transcript:
    return TranscriptBuilder().feed(body)
