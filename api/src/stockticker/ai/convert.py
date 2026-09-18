"""`useChat` request body and the UIMessage -> Anthropic message converter
(system design §6, "Request").

The server keeps no history; every request carries the whole conversation as
UIMessages. Their parts are validated at the boundary into `UIPart`, a
discriminated union that mirrors `UIMessagePart` in the `ai` package (v7).
A part type this server does not know becomes an `OtherPart`, so a newer
client never breaks the chat. A known type with a bad shape is dropped the
same way, so one malformed persisted part cannot 422 every later turn.
Conversion rules:

- `text` parts map to text blocks.
- Tool parts (`tool-<name>`, or `dynamic-tool`) map to a `tool_use` block in
  the assistant turn and a `tool_result` in the user turn after it. A finished
  call's output is shrunk to a `SUMMARY_BYTES` summary. A call left unfinished (no
  `output-available` or `output-error`, which is what a disconnect leaves
  behind) becomes an `is_error` result, so the model never believes it ran.
- `data-*`, every other part type, and system messages are dropped.
- An assistant message is split into one assistant turn per step
  (`step-start` parts), because a step's tool results must come before the
  next step's text.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from anthropic.types import MessageParam
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from stockticker.ai.serialize import compact_json, tool_result_block, wrap_untrusted, wrap_untrusted_cut

SUMMARY_BYTES = 2 * 1024
UNFINISHED_TOOL_RESULT = "This tool call never finished (the answer was interrupted). Its result is unknown."
_SUMMARY_SUFFIX = f"...[cut to {SUMMARY_BYTES // 1024} KB; run the query again to see more]"

# A turn under construction: {"role": ..., "content": [block dicts]}.
_Turn = dict[str, Any]


MAX_MESSAGES = 500
MAX_PARTS_PER_MESSAGE = 200
MAX_TEXT_PART_CHARS = 32_000


# --- UIMessage parts -----------------------------------------------------------


class TextPart(BaseModel):
    type: Literal["text"]
    text: str = Field(max_length=MAX_TEXT_PART_CHARS)


class StepStartPart(BaseModel):
    type: Literal["step-start"]


class OtherPart(BaseModel):
    """A part the converter drops unread: `data-*`, `reasoning`, `reasoning-file`,
    `file`, `source-url`, `source-document`, `custom`, and any part type a
    newer AI SDK adds. Only `type` is kept."""

    type: str


class ToolPart(BaseModel):
    """`tool-<name>`, or `dynamic-tool`, which names its tool in `toolName`."""

    type: str = Field(pattern=r"^(tool-.+|dynamic-tool)$")
    toolCallId: str = Field(min_length=1)  # noqa: N815 -- the AI SDK's field names
    toolName: str = Field(min_length=1)  # noqa: N815
    input: Any = None

    @model_validator(mode="before")
    @classmethod
    def _fill_tool_name(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("toolName"):
            return data
        part_type = data.get("type")
        if isinstance(part_type, str) and part_type.startswith("tool-"):
            return {**data, "toolName": part_type.removeprefix("tool-")}
        return data


class ToolOutputAvailable(ToolPart):
    state: Literal["output-available"]
    output: Any = None


class ToolOutputError(ToolPart):
    state: Literal["output-error"]
    errorText: str = ""  # noqa: N815


class ToolWithoutOutput(ToolPart):
    """Every other state: `input-streaming`, `input-available`,
    `approval-requested`, `approval-responded`, `output-denied`, and any state
    a newer AI SDK adds. The call has no result the model can see."""

    state: str = ""

    @field_validator("state", mode="before")
    @classmethod
    def _null_state_is_unfinished(cls, value: Any) -> Any:
        return "" if value is None else value


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _tool_state_tag(value: Any) -> str:
    state = _field(value, "state")
    return state if state in ("output-available", "output-error") else "without-output"


def _part_tag(value: Any) -> str | None:
    part_type = _field(value, "type")
    if not isinstance(part_type, str):
        return None
    if part_type in ("text", "step-start"):
        return part_type
    if part_type == "dynamic-tool" or part_type.startswith("tool-"):
        return "tool"
    return "other"


AnyToolPart = Annotated[
    Annotated[ToolOutputAvailable, Tag("output-available")]
    | Annotated[ToolOutputError, Tag("output-error")]
    | Annotated[ToolWithoutOutput, Tag("without-output")],
    Discriminator(_tool_state_tag),
]

UIPart = Annotated[
    Annotated[TextPart, Tag("text")]
    | Annotated[StepStartPart, Tag("step-start")]
    | Annotated[AnyToolPart, Tag("tool")]
    | Annotated[OtherPart, Tag("other")],
    Discriminator(_part_tag),
]

_part_adapter: TypeAdapter[UIPart] = TypeAdapter(UIPart)


class UIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    role: Literal["system", "user", "assistant"]
    parts: list[UIPart] = Field(default_factory=list, max_length=MAX_PARTS_PER_MESSAGE)

    @field_validator("parts", mode="before")
    @classmethod
    def _drop_malformed_parts(cls, parts: Any) -> Any:
        if not isinstance(parts, list):
            return parts
        kept: list[Any] = []
        for part in parts:
            try:
                kept.append(_part_adapter.validate_python(part))
            except ValidationError:
                continue
        return kept


class ChatRequest(BaseModel):
    """What `DefaultChatTransport` POSTs: `{id, messages, trigger, messageId}`
    plus any extra `body` fields the client adds, which are ignored."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    messages: list[UIMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    trigger: str | None = None
    messageId: str | None = None  # noqa: N815 -- the AI SDK's field name


# --- conversion ------------------------------------------------------------------


def summarize_output(output: Any) -> str:
    """A past tool output, as the model sees it on later turns: at most `SUMMARY_BYTES`,
    wrapped as untrusted data. Rows are dropped from the end first, so the
    columns and result metadata survive."""
    wrapped = wrap_untrusted(output)
    if len(wrapped.encode()) <= SUMMARY_BYTES:
        return wrapped
    if isinstance(output, dict) and isinstance(output.get("rows"), list):
        rows = list(output["rows"])
        while rows:
            rows = rows[: len(rows) // 2] if len(rows) > 8 else rows[:-1]
            candidate = wrap_untrusted(
                {**output, "rows": rows, "truncated": True, "rows_in_summary": len(rows)}
            )
            if len(candidate.encode()) <= SUMMARY_BYTES:
                return candidate
    return wrap_untrusted_cut(compact_json(output), max_bytes=SUMMARY_BYTES, marker=_SUMMARY_SUFFIX)


def _assistant_steps(parts: list[UIPart]) -> list[list[TextPart | ToolPart]]:
    steps: list[list[TextPart | ToolPart]] = [[]]
    for part in parts:
        if isinstance(part, StepStartPart):
            if steps[-1]:
                steps.append([])
            continue
        # Text after a tool call belongs to the next model call even when the
        # client dropped the step-start marker.
        if isinstance(part, TextPart) and any(isinstance(p, ToolPart) for p in steps[-1]):
            steps.append([])
        if isinstance(part, TextPart | ToolPart):
            steps[-1].append(part)
    return [step for step in steps if step]


def _tool_input(part: ToolPart) -> dict[str, Any]:
    return part.input if isinstance(part.input, dict) else {}


def _convert_assistant(parts: list[UIPart], tool_names: frozenset[str]) -> list[_Turn]:
    messages: list[_Turn] = []
    for step in _assistant_steps(parts):
        content: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for part in step:
            if isinstance(part, TextPart):
                if part.text.strip():
                    content.append({"type": "text", "text": part.text})
                continue
            if part.toolName not in tool_names:
                continue
            content.append(
                {"type": "tool_use", "id": part.toolCallId, "name": part.toolName, "input": _tool_input(part)}
            )
            results.append(_tool_result(part))
        if content:
            messages.append({"role": "assistant", "content": content})
        if results:
            messages.append({"role": "user", "content": results})
    return messages


def _tool_result(part: ToolPart) -> dict[str, Any]:
    if isinstance(part, ToolOutputAvailable):
        return tool_result_block(part.toolCallId, summarize_output(part.output))
    if isinstance(part, ToolOutputError):
        error_text = part.errorText or "The tool call failed."
        return tool_result_block(
            part.toolCallId, wrap_untrusted({"error": error_text[:SUMMARY_BYTES]}), is_error=True
        )
    return tool_result_block(
        part.toolCallId, wrap_untrusted({"error": UNFINISHED_TOOL_RESULT}), is_error=True
    )


def _convert_user(parts: list[UIPart]) -> list[_Turn]:
    content = [
        {"type": "text", "text": part.text}
        for part in parts
        if isinstance(part, TextPart) and part.text.strip()
    ]
    return [{"role": "user", "content": content}] if content else []


def to_anthropic_messages(messages: list[UIMessage], *, tool_names: frozenset[str]) -> list[MessageParam]:
    """`tool_names`: tool parts for any other name are dropped."""
    converted: list[_Turn] = []
    for message in messages:
        if message.role == "user":
            converted.extend(_convert_user(message.parts))
        elif message.role == "assistant":
            converted.extend(_convert_assistant(message.parts, tool_names))
    merged = _merge_same_role(converted)
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    while merged and merged[-1]["role"] != "user":
        merged.pop()
    return cast(list[MessageParam], merged)


def _merge_same_role(messages: list[_Turn]) -> list[_Turn]:
    """Consecutive same-role turns become one, keeping `tool_result` blocks
    first in a user turn, as the API requires."""
    merged: list[_Turn] = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            combined = merged[-1]["content"] + message["content"]
            if message["role"] == "user":
                combined.sort(key=lambda block: 0 if block.get("type") == "tool_result" else 1)
            merged[-1] = {"role": message["role"], "content": combined}
        else:
            merged.append({"role": message["role"], "content": list(message["content"])})
    return merged
