"""`useChat` request body and the UIMessage -> Anthropic message converter
(system design §6, "Request").

The server keeps no history; every request carries the whole conversation as
UIMessages. Conversion rules:

- `text` parts map to text blocks.
- Tool parts (`tool-<name>`, or `dynamic-tool`) map to a `tool_use` block in
  the assistant turn and a `tool_result` in the user turn after it. A finished
  call's output is shrunk to a 2 KB summary. A call left unfinished (no
  `output-available` or `output-error`, which is what a disconnect leaves
  behind) becomes an `is_error` result, so the model never believes it ran.
- `data-*`, `reasoning`, `file`, `source-*`, and system messages are dropped.
- An assistant message is split into one assistant turn per step
  (`step-start` parts), because a step's tool results must come before the
  next step's text.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from anthropic.types import MessageParam
from pydantic import BaseModel, ConfigDict, Field, field_validator

from stockticker.ai.serialize import wrap_untrusted

SUMMARY_BYTES = 2 * 1024
UNFINISHED_TOOL_RESULT = "This tool call never finished (the answer was interrupted). Its result is unknown."
_SUMMARY_SUFFIX = "...[cut to 2 KB; run the query again to see more]"

# A turn under construction: {"role": ..., "content": [block dicts]}.
_Turn = dict[str, Any]


MAX_MESSAGES = 500
MAX_PARTS_PER_MESSAGE = 200
MAX_TEXT_PART_CHARS = 32_000


class UIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    role: Literal["system", "user", "assistant"]
    parts: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_PARTS_PER_MESSAGE)

    @field_validator("parts")
    @classmethod
    def _text_parts_are_bounded(cls, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for part in parts:
            text = part.get("text")
            if isinstance(text, str) and len(text) > MAX_TEXT_PART_CHARS:
                raise ValueError(f"a text part is longer than {MAX_TEXT_PART_CHARS:,} characters")
        return parts


class ChatRequest(BaseModel):
    """What `DefaultChatTransport` POSTs: `{id, messages, trigger, messageId}`
    plus any extra `body` fields the client adds, which are ignored."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    messages: list[UIMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    trigger: str | None = None
    messageId: str | None = None  # noqa: N815 -- the AI SDK's field name


def _tool_name(part: dict[str, Any]) -> str | None:
    part_type = str(part.get("type", ""))
    if part_type == "dynamic-tool":
        name = part.get("toolName")
        return name if isinstance(name, str) else None
    if part_type.startswith("tool-"):
        return part_type.removeprefix("tool-")
    return None


def summarize_output(output: Any) -> str:
    """A past tool output, as the model sees it on later turns: at most 2 KB,
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
    text = json.dumps(output, separators=(",", ":"), ensure_ascii=False, default=str).replace("<", "\\u003c")
    budget = SUMMARY_BYTES - len(wrap_untrusted("").encode()) - len(_SUMMARY_SUFFIX.encode())
    cut = text.encode()[:budget].decode(errors="ignore")
    return f"<untrusted_data>{cut}{_SUMMARY_SUFFIX}</untrusted_data>"


def _assistant_steps(parts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    steps: list[list[dict[str, Any]]] = [[]]
    for part in parts:
        part_type = part.get("type")
        if part_type == "step-start":
            if steps[-1]:
                steps.append([])
            continue
        is_tool = _tool_name(part) is not None
        # Text after a tool call belongs to the next model call even when the
        # client dropped the step-start marker.
        if part_type == "text" and any(_tool_name(p) is not None for p in steps[-1]):
            steps.append([])
        if part_type == "text" or is_tool:
            steps[-1].append(part)
    return [step for step in steps if step]


def _convert_assistant(parts: list[dict[str, Any]], tool_names: frozenset[str]) -> list[_Turn]:
    messages: list[_Turn] = []
    for step in _assistant_steps(parts):
        content: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for part in step:
            if part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    content.append({"type": "text", "text": text})
                continue
            name = _tool_name(part)
            call_id = part.get("toolCallId")
            if name not in tool_names or not isinstance(call_id, str) or not call_id:
                continue
            tool_input = part.get("input")
            content.append(
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": tool_input if isinstance(tool_input, dict) else {},
                }
            )
            results.append(_tool_result(part, call_id))
        if content:
            messages.append({"role": "assistant", "content": content})
        if results:
            messages.append({"role": "user", "content": results})
    return messages


def _tool_result(part: dict[str, Any], call_id: str) -> dict[str, Any]:
    state = part.get("state")
    if state == "output-available":
        return {
            "type": "tool_result",
            "tool_use_id": call_id,
            "content": summarize_output(part.get("output")),
        }
    if state == "output-error":
        error_text = part.get("errorText") or "The tool call failed."
        return {
            "type": "tool_result",
            "tool_use_id": call_id,
            "is_error": True,
            "content": wrap_untrusted({"error": str(error_text)[:SUMMARY_BYTES]}),
        }
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "is_error": True,
        "content": wrap_untrusted({"error": UNFINISHED_TOOL_RESULT}),
    }


def _convert_user(parts: list[dict[str, Any]]) -> list[_Turn]:
    content = [
        {"type": "text", "text": part["text"]}
        for part in parts
        if part.get("type") == "text" and isinstance(part.get("text"), str) and part["text"].strip()
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
